"""Read-only, anonymous GitHub REST discovery with pinned source observations."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sce.core.models import Evidence
from .structured import DiscoveryLimits, SoftwareProject, observe_document, record_structure, selected_document


class DiscoveryError(ValueError):
    """A bounded discovery operation could not produce its declared observation."""


class JsonTransport(Protocol):
    def get_json(self, url: str, *, timeout: float, max_bytes: int) -> Any: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicGitHubTransport:
    """GET-only public API; no token access, redirects, arbitrary hosts, or downloads."""

    def get_json(self, url: str, *, timeout: float, max_bytes: int) -> Any:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise DiscoveryError("Public discovery transport accepts only https://api.github.com")
        request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Spider-Creator-Engine", "X-GitHub-Api-Version": "2022-11-28"}, method="GET")
        try:
            with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise DiscoveryError("GitHub response exceeded configured byte budget")
            return json.loads(raw)
        except HTTPError as exc:
            raise DiscoveryError(f"GitHub HTTP {exc.code}; repository may be unavailable, access limited, or the anonymous API rate limit exhausted") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise DiscoveryError(f"GitHub connection failed ({type(exc).__name__}); no observation established") from None
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, DiscoveryError):
                raise
            raise DiscoveryError("GitHub returned invalid JSON") from None


def valid_full_name(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", value)) and value.split("/")[1] not in {".", ".."}


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", value):
        raise DiscoveryError("GitHub response did not contain a valid pinned Git SHA")
    return value.lower()


class GitHubDiscovery:
    def __init__(self, *, limits: DiscoveryLimits, transport: JsonTransport | None = None):
        self.limits = limits
        self.transport = transport or PublicGitHubTransport()
        self.request_count = 0

    def _get(self, path: str) -> Any:
        if self.request_count >= self.limits.max_requests:
            raise DiscoveryError("GitHub request budget exhausted; discovery incomplete")
        self.request_count += 1
        return self.transport.get_json("https://api.github.com" + path, timeout=self.limits.timeout_seconds, max_bytes=self.limits.max_response_bytes)

    def candidates(self, kind: str, value: str, *, limit: int) -> tuple[list[str], list[str]]:
        names: list[str] = []
        limitations = ["Account/search candidates are bounded; discovery is not exhaustive or a suitability recommendation"]
        per_page = min(limit, 100)
        for page in range(1, self.limits.max_pages + 1):
            if kind == "github_account":
                payload = self._get(f"/users/{quote(value, safe='')}/repos?" + urlencode({"per_page": per_page, "page": page, "sort": "full_name", "type": "owner"}))
                candidates = payload
            else:
                payload = self._get("/search/repositories?" + urlencode({"q": value, "per_page": per_page, "page": page}))
                candidates = payload.get("items") if isinstance(payload, dict) else None
                if isinstance(payload, dict) and payload.get("incomplete_results"):
                    limitations.append("GitHub reports incomplete search results")
            if not isinstance(candidates, list):
                raise DiscoveryError("GitHub returned an invalid repository listing")
            for candidate in candidates:
                if isinstance(candidate, dict) and valid_full_name(candidate.get("full_name")) and candidate.get("private") is False and candidate["full_name"] not in names:
                    names.append(candidate["full_name"])
                if len(names) >= limit:
                    return names, limitations
            if len(candidates) < per_page:
                break
        return names, limitations

    def inspect(self, full_name: str) -> SoftwareProject:
        if not valid_full_name(full_name):
            raise DiscoveryError("Invalid GitHub owner/repository")
        endpoint = f"/repos/{full_name}"
        metadata = self._get(endpoint)
        if not isinstance(metadata, dict) or not valid_full_name(metadata.get("full_name")) or type(metadata.get("id")) is not int:
            raise DiscoveryError("GitHub returned invalid repository metadata")
        if metadata.get("private") is not False:
            raise DiscoveryError("Only public GitHub repository discovery is supported")
        canonical_name = metadata["full_name"]
        uri = "https://github.com/" + canonical_name
        project = SoftwareProject(f"github:{metadata['id']}", uri, canonical_name, None, "github_repository")
        project.metadata = {key: metadata.get(key) for key in ("description", "default_branch", "archived", "fork", "license", "homepage", "topics")}
        project.evidence.append(Evidence("https://api.github.com" + endpoint, "Observed public repository metadata; descriptive and license fields are author/platform declarations", kind="repository_metadata"))
        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise DiscoveryError("Repository has no resolvable default branch")
        commit_url = endpoint + "/commits/" + quote(branch, safe="")
        commit = self._get(commit_url)
        try:
            project.revision = _sha(commit["sha"])
            tree_sha = _sha(commit["commit"]["tree"]["sha"])
        except (KeyError, TypeError):
            raise DiscoveryError("GitHub returned invalid commit metadata") from None
        project.evidence.append(Evidence("https://api.github.com" + commit_url, f"Pinned default branch to commit {project.revision}; subsequent source observations use its tree or blob IDs", kind="source_revision"))
        tree_url = endpoint + f"/git/trees/{tree_sha}?recursive=1"
        tree = self._get(tree_url)
        if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list) or _sha(tree.get("sha")) != tree_sha:
            raise DiscoveryError("GitHub returned invalid or mismatched source tree")
        if tree.get("truncated"):
            project.limitations.append("GitHub truncated the source tree; inventory incomplete")
        entries: list[dict] = []
        for item in tree["tree"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                project.limitations.append("Malformed source tree entry skipped")
                continue
            if item.get("type") != "blob" or item.get("mode") not in {"100644", "100755"}:
                continue
            if len(entries) >= self.limits.max_files:
                project.limitations.append("File budget reached; source tree observation incomplete")
                break
            entries.append(item)
        paths = [item["path"] for item in entries]
        record_structure(project, paths, "https://api.github.com" + tree_url)
        project.evidence.append(Evidence("https://api.github.com" + tree_url, f"Observed {len(paths)} regular-file paths at commit {project.revision}; links and submodules are not followed", kind="source_tree"))
        selected = [item for item in entries if selected_document(item["path"])]
        # At most one README plus four supported manifest kinds.
        readme_seen = False
        documents = []
        for item in sorted(selected, key=lambda item: item["path"]):
            if item["path"].casefold().startswith("readme"):
                if readme_seen:
                    continue
                readme_seen = True
            documents.append(item)
        for item in documents[:5]:
            name = item["path"]
            if type(item.get("size")) is not int or item["size"] < 0 or item["size"] > self.limits.max_file_bytes:
                project.limitations.append(f"Document size unknown or exceeds text budget: {name}")
                continue
            try:
                blob_sha = _sha(item.get("sha"))
                blob = self._get(endpoint + f"/git/blobs/{blob_sha}")
                if not isinstance(blob, dict) or blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str) or _sha(blob.get("sha")) != blob_sha:
                    raise DiscoveryError("Invalid source blob response")
                raw = base64.b64decode("".join(blob["content"].split()), validate=True)
                if len(raw) > self.limits.max_file_bytes or len(raw) != item["size"]:
                    raise DiscoveryError("Source blob does not match declared size or text budget")
                actual_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
                if actual_sha != blob_sha:
                    raise DiscoveryError("Source blob Git hash differs from pinned tree")
                observe_document(project, name, raw, f"{uri}/blob/{project.revision}/{quote(name, safe='/')}")
            except (DiscoveryError, ValueError) as exc:
                project.limitations.append(f"Document not observed ({name}): {exc}")
        project.limitations.append("No repository code was acquired for execution, imported, built, installed, or functionally verified")
        project.metadata["api_requests_used"] = self.request_count
        return project
