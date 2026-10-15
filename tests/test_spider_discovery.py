import base64
import hashlib
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from sce.core.models import jsonable
from sce.discovery import DiscoveryLimits, SpiderDiscovery, StartingPoint, inspect_local
from sce.discovery.github import DiscoveryError, PublicGitHubTransport


COMMIT = "a" * 40
TREE = "b" * 40


class FakeGitHub:
    def __init__(self, *, truncated=False, corrupt_blob=False):
        self.calls = []
        self.docs = {"README.md": b"# Useful sample\nA small Python application.\n", "pyproject.toml": b'[project]\nname="sample"\ndependencies=["example>=1"]\n[build-system]\nbuild-backend="setuptools.build_meta"\n'}
        self.hashes = {name: hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() for name, raw in self.docs.items()}
        self.truncated = truncated
        self.corrupt_blob = corrupt_blob

    def get_json(self, url, *, timeout, max_bytes):
        self.calls.append(url)
        assert timeout > 0 and max_bytes > 0
        endpoint = url.removeprefix("https://api.github.com")
        if endpoint.startswith("/search/repositories?"):
            return {"items": [{"full_name": "owner/sample", "private": False}], "incomplete_results": True}
        if endpoint.startswith("/users/owner/repos?"):
            return [{"full_name": "owner/sample", "private": False}]
        if endpoint == "/repos/owner/sample":
            return {"id": 12, "full_name": "owner/sample", "private": False, "default_branch": "main", "description": "Sample"}
        if endpoint.endswith("/commits/main"):
            return {"sha": COMMIT, "commit": {"tree": {"sha": TREE}}}
        if endpoint.endswith(f"/git/trees/{TREE}?recursive=1"):
            return {"sha": TREE, "truncated": self.truncated, "tree": [{"path": name, "type": "blob", "mode": "100644", "size": len(raw), "sha": self.hashes[name]} for name, raw in self.docs.items()] + [{"path": "sample.py", "type": "blob", "mode": "100644", "sha": "c" * 40, "size": 9}]}
        for name, sha in self.hashes.items():
            if endpoint.endswith("/git/blobs/" + sha):
                raw = self.docs[name]
                if self.corrupt_blob:
                    raw = b"X" * len(raw)
                return {"sha": sha, "encoding": "base64", "content": base64.b64encode(raw).decode()}
        raise AssertionError(f"Unexpected API request: {endpoint}")


@pytest.mark.parametrize(("text", "kind", "value"), [
    ("https://github.com/owner/sample.git", "github_repository", "owner/sample"),
    ("owner/sample", "github_repository", "owner/sample"),
    ("https://github.com/owner", "github_account", "owner"),
    ("@owner", "github_account", "owner"),
    ("github:owner", "github_account", "owner"),
    ("find Python GPU monitoring tools", "query", "find Python GPU monitoring tools"),
    ("https://sourceforge.net/projects/test", "sourceforge", "https://sourceforge.net/projects/test"),
    ("https://www.mediafire.com/file/example", "mediafire", "https://www.mediafire.com/file/example"),
    ("https://example.com/tool.zip", "direct_url", "https://example.com/tool.zip"),
    ("https://github.com/owner/sample/tree/main", "unsupported_github_url", "https://github.com/owner/sample/tree/main"),
])
def test_normalize_starting_points(text, kind, value):
    point = StartingPoint.normalize(text)
    assert (point.kind, point.value) == (kind, value)


def test_local_inspection_has_structure_provenance_and_content_identity(tmp_path):
    source = tmp_path / "sample"
    source.mkdir()
    (source / "README.md").write_text("# Small project", encoding="utf-8")
    (source / "pyproject.toml").write_text('[project]\ndependencies=["widget>=1"]\n[build-system]\nbuild-backend="setuptools.build_meta"', encoding="utf-8")
    (source / "sample.py").write_text('raise RuntimeError("must never execute during discovery")', encoding="utf-8")
    project = inspect_local(source)
    assert project.metadata["languages"] == ["Python"]
    assert project.metadata["dependencies"] == ["widget>=1"]
    assert any(item.provenance == "AUTHOR_DOCUMENTATION" for item in project.observations)
    assert len(project.metadata["content_hashes"]) == 3
    assert project.evidence
    json.dumps(jsonable(project))
    renamed = tmp_path / "moved"
    source.rename(renamed)
    moved = inspect_local(renamed)
    assert moved.resource_id == project.resource_id
    assert moved.source_uri != project.source_uri
    (renamed / "sample.py").write_text("changed", encoding="utf-8")
    assert inspect_local(renamed).resource_id != project.resource_id


def test_local_file_uri_missing_path_and_archive(tmp_path):
    archive = tmp_path / "resource.zip"
    archive.write_bytes(b"not an executable archive")
    assert StartingPoint.normalize(archive.as_uri()).kind == "local"
    result = SpiderDiscovery().discover(archive.as_uri())
    assert result.projects[0].metadata["content_hashes"]
    assert any("not extracted" in item for item in result.projects[0].limitations)
    missing = SpiderDiscovery().discover(tmp_path / "missing")
    assert missing.errors and not missing.projects


def test_local_budgets_and_excluded_environment(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "hidden.py").write_text("ignored")
    (tmp_path / "a.py").write_text("one")
    (tmp_path / "b.py").write_text("two")
    project = inspect_local(tmp_path, limits=DiscoveryLimits(max_files=1, max_source_bytes=1))
    assert project.metadata["structure"] == ["a.py"]
    assert project.metadata["content_hashes"] == {}
    assert any("File budget" in item for item in project.limitations)
    assert any("Source byte budget" in item for item in project.limitations)
    assert any(".venv" in item for item in project.limitations)


def test_malformed_local_manifest_remains_observation(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies="wrong"')
    project = inspect_local(tmp_path)
    assert project.observations[0].subject == "pyproject.toml"
    assert any("Could not parse" in item for item in project.limitations)


def test_offline_never_calls_transport(tmp_path):
    class NeverNetwork:
        def get_json(self, *args, **kwargs):
            pytest.fail("Offline discovery attempted network access")
    spider = SpiderDiscovery(transport=NeverNetwork())
    assert spider.discover("owner/sample").errors
    assert spider.discover("find a useful application").errors
    assert spider.discover(tmp_path).projects


@pytest.mark.parametrize("url", ["https://sourceforge.net/projects/a", "https://mediafire.com/file/x", "https://example.org/file.zip"])
def test_proposed_connectors_are_not_silently_executed(url):
    transport = FakeGitHub()
    result = SpiderDiscovery(offline=False, transport=transport).discover(url)
    assert result.unsupported and not result.projects
    assert not transport.calls


def test_github_inspection_pins_revision_and_verifies_blob_hash():
    transport = FakeGitHub()
    result = SpiderDiscovery(offline=False, transport=transport).discover("owner/sample")
    assert not result.errors
    project = result.projects[0]
    assert project.resource_id == "github:12" and project.revision == COMMIT
    assert project.metadata["dependencies"] == ["example>=1"]
    assert project.metadata["languages"] == ["Python"]
    assert all(COMMIT in item.source for item in project.observations if item.provenance == "AUTHOR_DOCUMENTATION")
    assert len(transport.calls) == 5
    assert all("api.github.com/" in url for url in transport.calls)


def test_corrupt_blob_does_not_become_author_documentation():
    result = SpiderDiscovery(offline=False, transport=FakeGitHub(corrupt_blob=True)).discover("owner/sample")
    project = result.projects[0]
    assert not any(item.provenance == "AUTHOR_DOCUMENTATION" for item in project.observations)
    assert any("Git hash differs" in item for item in project.limitations)


def test_github_truncation_and_request_budget_remain_explicit():
    project = SpiderDiscovery(offline=False, transport=FakeGitHub(truncated=True), limits=DiscoveryLimits(max_requests=3)).discover("owner/sample").projects[0]
    assert any("truncated" in item for item in project.limitations)
    assert any("request budget" in item for item in project.limitations)
    failed = SpiderDiscovery(offline=False, transport=FakeGitHub(), limits=DiscoveryLimits(max_requests=1)).discover("owner/sample")
    assert not failed.projects and "request budget" in failed.errors[0]


@pytest.mark.parametrize("query", ["@owner", "Python sample application"])
def test_account_and_query_discovery_produce_inspected_projects(query):
    transport = FakeGitHub()
    result = SpiderDiscovery(offline=False, transport=transport).discover(query, limit=1)
    assert result.projects[0].revision == COMMIT
    assert result.projects[0].metadata["dependencies"]
    assert result.limitations
    assert len(transport.calls) == 6


def test_transport_enforces_body_budget_and_host(monkeypatch):
    class Response(io.BytesIO):
        pass
    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            assert "Authorization" not in request.headers
            return Response(b'{"huge":"' + b"x" * 100 + b'"}')
    monkeypatch.setattr("sce.discovery.github.build_opener", lambda *args: Opener())
    transport = PublicGitHubTransport()
    with pytest.raises(DiscoveryError, match="byte budget"):
        transport.get_json("https://api.github.com/repos/a/b", timeout=1, max_bytes=10)
    with pytest.raises(DiscoveryError, match="only https"):
        transport.get_json("http://127.0.0.1/", timeout=1, max_bytes=10)


def test_transport_http_error_is_truthful_and_does_not_include_body(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 403, "secret body must not appear", {}, None)
    monkeypatch.setattr("sce.discovery.github.build_opener", lambda *args: Opener())
    with pytest.raises(DiscoveryError, match="GitHub HTTP 403") as captured:
        PublicGitHubTransport().get_json("https://api.github.com/repos/a/b", timeout=1, max_bytes=10)
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize("kwargs", [{"max_pages": 0}, {"max_files": -1}, {"timeout_seconds": 121}, {"max_requests": True}])
def test_invalid_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        DiscoveryLimits(**kwargs)
