"""Bounded static project observations; no project code is imported or executed."""

from pathlib import Path
import hashlib
import os
import tomllib

from sce.core.models import Evidence, jsonable


def analyze_local(source: Path, *, max_files: int = 1000) -> dict:
    if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
        raise ValueError("Linked analysis roots are unsupported")
    source = source.resolve(strict=True)
    if not source.is_dir() or not 1 <= max_files <= 10000:
        raise ValueError("Analysis requires directory and max_files 1..10000")
    languages = set()
    structure = []
    unknowns = ["Static observations do not establish buildability, interfaces, or integration compatibility"]
    extensions = {".py": "Python", ".cs": "C#", ".rs": "Rust", ".js": "JavaScript", ".ts": "TypeScript"}
    def regular_files():
        directories_seen = 0
        def inaccessible(error):
            unknowns.append(f"Directory could not be inspected: {error}")
        for root, directories, files in os.walk(source, followlinks=False, onerror=inaccessible):
            directories_seen += 1
            if directories_seen > max_files:
                unknowns.append("Directory budget reached; inventory incomplete")
                return
            kept = []
            for name in directories:
                path = Path(root) / name
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    unknowns.append(f"Linked directory skipped: {path.relative_to(source)}")
                else:
                    kept.append(name)
            directories[:] = sorted(kept)
            for name in sorted(files):
                path = Path(root) / name
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    unknowns.append(f"Linked path skipped: {path.relative_to(source)}")
                elif path.is_file():
                    yield path
    for path in regular_files():
        if len(structure) >= max_files:
            unknowns.append("File budget reached; inventory incomplete")
            break
        relative = path.relative_to(source).as_posix()
        structure.append(relative)
        if path.suffix in extensions:
            languages.add(extensions[path.suffix])
    dependencies = []
    build_systems = []
    metadata_evidence = []
    if "pyproject.toml" in structure:
        path = source / "pyproject.toml"
        if path.stat().st_size > 100_000:
            unknowns.append("pyproject.toml exceeds metadata budget")
        else:
            try:
                with path.open("rb") as stream:
                    raw = stream.read(100_001)
                if len(raw) > 100_000:
                    raise ValueError("pyproject.toml grew beyond metadata budget")
                metadata = tomllib.loads(raw.decode("utf-8"))
                project, system = metadata.get("project", {}), metadata.get("build-system", {})
                if not isinstance(project, dict) or not isinstance(system, dict):
                    raise ValueError("project and build-system metadata must be tables")
                declared_dependencies = project.get("dependencies", [])
                if not isinstance(declared_dependencies, list) or any(not isinstance(item, str) for item in declared_dependencies):
                    raise ValueError("project.dependencies must be an array of strings")
                backend = system.get("build-backend", "unknown Python backend")
                if not isinstance(backend, str):
                    raise ValueError("build-system.build-backend must be a string")
                dependencies = declared_dependencies
                build_systems = [backend]
                metadata_evidence.append(jsonable(Evidence(path.as_uri(), f"Parsed declared metadata; SHA-256 {hashlib.sha256(raw).hexdigest()}")))
            except (ValueError, OSError) as exc:
                unknowns.append(f"Could not parse Python metadata: {exc}")
    if any(name.endswith((".csproj", ".sln", ".slnx")) for name in structure):
        build_systems.append("MSBuild/.NET candidate (unverified)")
    return {"source": source.as_uri(), "languages": sorted(languages), "structure": structure,
            "dependencies": dependencies, "build_systems": build_systems,
            "entry_points": [name for name in structure if name.endswith("__main__.py")],
            "candidate_integration_methods": ["CLI wrapper, only after interface inspection"] if "__main__.py" in structure else [],
            "required_tools": ["Python"] if "Python" in languages else [],
            "evidence": [jsonable(Evidence(source.as_uri(), "Bounded static filename observations; languages inferred from suffixes")), *metadata_evidence],
            "unknowns": unknowns}
