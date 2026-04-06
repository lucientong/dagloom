#!/usr/bin/env python3
"""ETL Pipeline Example — Dagloom

Demonstrates a realistic Extract-Transform-Load pipeline:
  fetch_data >> validate >> clean >> transform >> save

Run with:
    python examples/etl_example.py
"""

from dagloom import node


@node(retry=3, timeout=30.0)
def fetch_data(url: str) -> list[dict]:
    """Fetch raw data from an HTTP endpoint."""
    # Simulated fetch — in production, use httpx or requests.
    print(f"  Fetching data from {url} ...")
    return [
        {"name": "Alice", "age": 30, "score": 95.5, "city": "NYC"},
        {"name": "Bob", "age": None, "score": 87.2, "city": "LA"},
        {"name": "Charlie", "age": 25, "score": None, "city": "NYC"},
        {"name": "Diana", "age": 28, "score": 91.0, "city": "SF"},
        {"name": "Eve", "age": 35, "score": 78.3, "city": None},
    ]


@node
def validate(records: list[dict]) -> list[dict]:
    """Validate data schema — ensure required fields exist."""
    required = {"name", "age", "score", "city"}
    for i, record in enumerate(records):
        missing = required - set(record.keys())
        if missing:
            raise ValueError(f"Row {i}: missing fields {missing}")
    print(f"  Validated {len(records)} records — schema OK")
    return records


@node(cache=True)
def clean(records: list[dict]) -> list[dict]:
    """Remove records with missing values."""
    before = len(records)
    cleaned = [r for r in records if all(v is not None for v in r.values())]
    after = len(cleaned)
    print(f"  Cleaned: {before} -> {after} records ({before - after} dropped)")
    return cleaned


@node
def transform(records: list[dict]) -> list[dict]:
    """Apply transformations: normalize scores, add derived fields."""
    max_score = max(r["score"] for r in records)
    for r in records:
        r["score_normalized"] = round(r["score"] / max_score, 3)
        r["is_senior"] = r["age"] >= 30
    print(f"  Transformed {len(records)} records")
    return records


@node
def save(records: list[dict]) -> str:
    """Save processed data to a file."""
    path = "output/etl_result.json"
    print(f"  Saving {len(records)} records to {path}")
    # In production: write to parquet, DB, or S3.
    return f"Saved {len(records)} records to {path}"


# Build the ETL pipeline with >> operator.
pipeline = fetch_data >> validate >> clean >> transform >> save

if __name__ == "__main__":
    print("=" * 50)
    print("  Dagloom ETL Pipeline Example")
    print("=" * 50)
    print()

    result = pipeline.run(url="https://api.example.com/data")
    print()
    print(f"Result: {result}")

    print()
    print("Pipeline structure:")
    print(pipeline.visualize())
