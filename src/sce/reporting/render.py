"""Render one canonical record without inferring missing verification."""

import html
import json
from pathlib import Path

from sce.core.models import OperationRecord, jsonable


def render_report(record: OperationRecord, format: str = "json") -> str:
    payload = json.dumps(jsonable(record), indent=2, ensure_ascii=False, allow_nan=False)
    if format == "json":
        return payload + "\n"
    if format == "markdown":
        # A dynamic fence prevents source output containing backticks escaping it.
        fence = "`" * max(3, max((len(part) for part in __import__('re').findall(r'`+', payload)), default=0) + 1)
        return (f"# SCE operation {html.escape(record.id)}\n\n"
                f"Outcome: **{record.outcome.value}**\n\n"
                f"Verification: **{record.verification.value}**\n\n"
                f"{fence}json\n{payload}\n{fence}\n")
    if format == "html":
        return ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                "<title>SCE operation report</title><body><h1>SCE operation report</h1>"
                f"<p>Outcome: <strong>{record.outcome.value}</strong></p>"
                f"<p>Verification: <strong>{record.verification.value}</strong></p>"
                f"<pre>{html.escape(payload)}</pre></body></html>\n")
    raise ValueError(f"Unsupported report format: {format}")


def write_report(record: OperationRecord, destination: Path, format: str = "json") -> Path:
    # Never overwrite prior operation evidence.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(render_report(record, format))
    return destination
