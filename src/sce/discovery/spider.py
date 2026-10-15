"""Normalize multiple human starting points and route only implemented providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from .github import DiscoveryError, GitHubDiscovery, JsonTransport, valid_full_name
from .structured import DiscoveryLimits, DiscoveryResult, inspect_local


@dataclass(frozen=True)
class StartingPoint:
    original: str
    kind: str
    value: str

    @classmethod
    def normalize(cls, text: str | Path) -> StartingPoint:
        value = str(text).strip()
        if not value:
            raise ValueError("A discovery starting point is required")
        if len(value) > 2000:
            raise ValueError("Discovery starting point exceeds 2000 characters")
        if Path(value).exists() or re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("./", "../", "/", ".\\", "..\\", "\\\\")):
            return cls(value, "local", value)
        parsed = urlsplit(value)
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                return cls(value, "unsupported_url", value)
            return cls(value, "local", url2pathname(parsed.path))
        if parsed.scheme in {"http", "https"}:
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                return cls(value, "unsupported_url", value)
            host = (parsed.hostname or "").lower()
            pieces = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
            if host == "github.com" and parsed.scheme == "https" and parsed.port in {None, 443}:
                if len(pieces) == 1 and re.fullmatch(r"[A-Za-z0-9-]+", pieces[0]):
                    return cls(value, "github_account", pieces[0])
                if len(pieces) == 2:
                    full_name = "/".join(pieces).removesuffix(".git")
                    if valid_full_name(full_name):
                        return cls(value, "github_repository", full_name)
                return cls(value, "unsupported_github_url", value)
            if host == "sourceforge.net" or host.endswith(".sourceforge.net"):
                return cls(value, "sourceforge", value)
            if host in {"mediafire.com", "www.mediafire.com"}:
                return cls(value, "mediafire", value)
            return cls(value, "direct_url", value)
        if value.startswith("@") and re.fullmatch(r"@[A-Za-z0-9-]+", value):
            return cls(value, "github_account", value[1:])
        if value.startswith("github:"):
            candidate = value.removeprefix("github:")
            if valid_full_name(candidate):
                return cls(value, "github_repository", candidate)
            if re.fullmatch(r"[A-Za-z0-9-]+", candidate):
                return cls(value, "github_account", candidate)
            raise ValueError("Invalid github: starting point")
        if valid_full_name(value):
            return cls(value, "github_repository", value)
        if parsed.scheme:
            return cls(value, "unsupported_url", value)
        return cls(value, "query", value)


class SpiderDiscovery:
    """Local-first discovery. Internet requests require offline=False explicitly."""

    def __init__(self, *, offline: bool = True, limits: DiscoveryLimits | None = None, transport: JsonTransport | None = None):
        self.offline = offline
        self.limits = limits or DiscoveryLimits()
        self.transport = transport

    def discover(self, start: str | Path | StartingPoint, *, limit: int = 5) -> DiscoveryResult:
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Discovery limit must be 1..20")
        point = start if isinstance(start, StartingPoint) else StartingPoint.normalize(start)
        result = DiscoveryResult(asdict(point), online=not self.offline)
        if point.kind == "local":
            try:
                result.projects.append(inspect_local(point.value, limits=self.limits))
            except (OSError, ValueError) as exc:
                result.errors.append(f"Local inspection failed: {exc}")
            return result
        if point.kind not in {"github_repository", "github_account", "query"}:
            result.unsupported.append(f"{point.kind}: source classified only; discovery/acquisition connector is PROPOSED. Supply a local path or a GitHub repository/account URL.")
            return result
        if self.offline:
            result.errors.append("Online discovery is disabled in offline mode; use an explicit local path or opt into online discovery")
            return result
        provider = GitHubDiscovery(limits=self.limits, transport=self.transport)
        try:
            if point.kind == "github_repository":
                names = [point.value]
            else:
                names, limitations = provider.candidates(point.kind, point.value, limit=limit)
                result.limitations.extend(limitations)
                if point.kind == "query":
                    result.limitations.append("Natural-language input is a literal GitHub keyword search; semantic objective decomposition is PROPOSED")
            for name in names:
                try:
                    result.projects.append(provider.inspect(name))
                except DiscoveryError as exc:
                    result.errors.append(f"{name}: {exc}")
        except DiscoveryError as exc:
            result.errors.append(str(exc))
        return result
