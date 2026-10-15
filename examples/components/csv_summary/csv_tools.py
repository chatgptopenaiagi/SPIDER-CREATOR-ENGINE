"""A reusable CSV analysis component using the Python standard library."""

import csv
import io


def summarize(request):
    """Count rows, columns, and distinct values without evaluating CSV contents."""
    text = request.get("csv_text")
    if not isinstance(text, str):
        raise ValueError("csv_text must be a string")
    reader = csv.DictReader(io.StringIO(text))
    columns = reader.fieldnames
    if not columns or len(columns) != len(set(columns)) or any(not name for name in columns):
        raise ValueError("CSV requires a nonempty header with distinct nonempty column names")
    unique = {name: set() for name in columns}
    row_count = 0
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Every CSV row must have the declared number of columns")
        row_count += 1
        for name in columns:
            unique[name].add(row[name])
    return {"row_count": row_count, "column_count": len(columns), "columns": columns,
            "distinct_values": {name: len(unique[name]) for name in columns}}
