"""Read local observations without assuming the user's reported specifications."""

from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def _memory() -> dict:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        "total_physical", "available_physical", "total_pagefile",
                        "available_pagefile", "total_virtual", "available_virtual", "extended_virtual",
                    )
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                raise OSError("GlobalMemoryStatusEx failed")
            return {"total_bytes": status.total_physical, "available_bytes": status.available_physical,
                    "source": "GlobalMemoryStatusEx", "error": None}
        if hasattr(os, "sysconf"):
            return {"total_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
                    "available_bytes": None, "source": "os.sysconf", "error": None}
    except (OSError, ValueError, AttributeError) as error:
        return {"total_bytes": None, "available_bytes": None, "source": None, "error": str(error)}
    return {"total_bytes": None, "available_bytes": None, "source": None, "error": "unsupported platform"}


def discover_environment(storage_path: Path | str, *, probe_gpu: bool = False) -> dict:
    """Observe the supplied volume, never create or silently substitute storage."""
    observed = datetime.now(timezone.utc).isoformat()
    destination = Path(storage_path).expanduser().resolve()
    try:
        usage = shutil.disk_usage(destination)
        disk = {"path": str(destination), "total_bytes": usage.total, "free_bytes": usage.free, "error": None}
    except OSError as error:
        disk = {"path": str(destination), "total_bytes": None, "free_bytes": None, "error": str(error)}
    gpu: dict = {"status": "not_probed", "devices": [], "error": None}
    gpu_tool = shutil.which("nvidia-smi")
    if probe_gpu:
        if gpu_tool is None:
            gpu = {"status": "unavailable", "devices": [], "error": "nvidia-smi not found"}
        else:
            try:
                result = subprocess.run(
                    [gpu_tool, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                if result.returncode:
                    gpu = {"status": "failed", "devices": [], "error": result.stderr[:2000]}
                else:
                    devices = []
                    for line in result.stdout.splitlines():
                        name, total, used = (part.strip() for part in line.rsplit(",", 2))
                        devices.append({"name": name, "total_bytes": int(total) * 1024**2,
                                        "used_bytes": int(used) * 1024**2})
                    gpu = {"status": "observed", "devices": devices, "error": None}
            except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                gpu = {"status": "failed", "devices": [], "error": str(error)}
    return {
        "observed_at": observed,
        "platform": platform.platform(),
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "cpu": {"description": platform.processor() or None, "logical_count": os.cpu_count()},
        "memory": _memory(), "disk": disk, "gpu": gpu,
        "tools": {name: shutil.which(name) for name in ("python", "git", "gh", "dotnet", "nvidia-smi")},
        "limitations": ["Point-in-time observations, not reservations or resource enforcement.",
                         "No model offload configuration inferred from GPU memory."],
    }
