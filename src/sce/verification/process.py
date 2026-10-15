"""Bounded direct-process checks for explicitly trusted programs.

This is not an operating-system sandbox. The timeout applies to the immediate
process; arbitrary descendants and OS resource quotas are not controlled here.
"""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Callable, Sequence


@dataclass(frozen=True)
class ProcessVerification:
    status: str
    argv: tuple[str, ...]
    expected_stdout: str
    expected_exit: int
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    detail: str = ""
    elapsed_seconds: float = 0.0


def verify_process(
    argv: Sequence[str], *, cwd: Path, expected_stdout: str,
    expected_exit: int, timeout_seconds: float,
    cancelled: Callable[[], bool] | None = None, max_output_bytes: int = 1_000_000,
) -> ProcessVerification:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    command = tuple(str(arg) for arg in argv)
    started = time.monotonic()
    base = dict(argv=command, expected_stdout=expected_stdout, expected_exit=expected_exit)
    if cancelled and cancelled():
        return ProcessVerification(status="inconclusive", detail="cancelled before verification", **base)
    try:
        # File-backed capture avoids pipe-reader waits on descendants that inherit
        # output handles. Captured evidence is bounded; process-tree isolation is
        # still outside this adapter's contract.
        with tempfile.TemporaryFile(dir=cwd) as output, tempfile.TemporaryFile(dir=cwd) as errors:
            with subprocess.Popen(command, cwd=cwd, stdout=output, stderr=errors, stdin=subprocess.DEVNULL, shell=False) as process:
                interrupted = ""
                while True:
                    elapsed = time.monotonic() - started
                    if cancelled and cancelled():
                        interrupted = "cancelled during verification"
                    elif elapsed >= timeout_seconds:
                        interrupted = "verification timed out"
                    elif os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > max_output_bytes:
                        interrupted = "verification output limit exceeded"
                    if interrupted:
                        process.kill()
                        process.wait(timeout=2)
                        break
                    try:
                        process.wait(timeout=min(0.05, timeout_seconds - elapsed))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > max_output_bytes:
                    interrupted = interrupted or "verification output limit exceeded"
                output.seek(0)
                errors.seek(0)
                stdout = output.read(max_output_bytes).decode("utf-8", errors="replace").replace("\r\n", "\n")
                stderr = errors.read(max_output_bytes).decode("utf-8", errors="replace").replace("\r\n", "\n")
                if interrupted:
                    return ProcessVerification(
                        status="inconclusive", stdout=stdout, stderr=stderr,
                        exit_code=process.returncode, detail=interrupted,
                        elapsed_seconds=time.monotonic() - started, **base,
                    )
            passed = process.returncode == expected_exit and stdout == expected_stdout
            return ProcessVerification(
                status="passed" if passed else "failed", stdout=stdout, stderr=stderr,
                exit_code=process.returncode,
                detail="declared exit and stdout matched" if passed else "declared exit or stdout did not match",
                elapsed_seconds=time.monotonic() - started, **base,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProcessVerification(
            status="inconclusive", detail=f"could not launch verification: {exc}",
            elapsed_seconds=time.monotonic() - started, **base,
        )
