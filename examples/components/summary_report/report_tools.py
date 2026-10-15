"""A separate presentation component accepting a JSON-compatible summary."""


def format_report(summary):
    """Preserve structured statistics and add a readable report."""
    columns = summary["columns"]
    lines = [f"Rows: {summary['row_count']}", f"Columns: {summary['column_count']}"]
    lines.extend(f"{name}: {summary['distinct_values'][name]} distinct values" for name in columns)
    return {**summary, "report": "\n".join(lines)}
