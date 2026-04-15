"""Demo ETL pipeline — exercises core Dagloom features.

This self-contained pipeline demonstrates:
- ``@node`` decorator with retry, cache, and timeout
- ``>>`` operator for DAG construction
- ``|`` operator for conditional branching
- Pipeline scheduling (``schedule=``)
- Notification configuration (``notify_on=``)

The pipeline simulates a mini ETL flow:

    generate_data → validate → (clean_data | flag_anomalies) → summarize → report

No external dependencies required — all data is generated in-memory.
"""

from __future__ import annotations

import logging
import random
import statistics
from datetime import UTC, datetime

from dagloom.core.node import node
from dagloom.core.pipeline import Pipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node definitions
# ---------------------------------------------------------------------------


@node(cache=True, timeout=10.0)
def generate_data(num_records: int = 100, seed: int = 42) -> list[dict]:
    """Generate sample sales records.

    Produces a list of dicts with fields: id, product, amount, region, timestamp.
    """
    rng = random.Random(seed)
    products = ["Widget A", "Widget B", "Gadget X", "Gadget Y", "Tool Z"]
    regions = ["North", "South", "East", "West"]

    records = []
    for i in range(num_records):
        record = {
            "id": i + 1,
            "product": rng.choice(products),
            "amount": round(rng.uniform(10.0, 500.0), 2),
            "region": rng.choice(regions),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # Inject ~5% anomalies (negative amounts).
        if rng.random() < 0.05:
            record["amount"] = -abs(record["amount"])
        records.append(record)

    logger.info("Generated %d records.", len(records))
    return records


@node(cache=True)
def validate(records: list[dict]) -> dict:
    """Validate records and route to appropriate handler.

    Returns a dict with ``"branch"`` key for conditional routing:
    - ``"clean_data"`` if anomaly rate < 10%
    - ``"flag_anomalies"`` if anomaly rate >= 10%
    """
    total = len(records)
    anomalies = sum(1 for r in records if r["amount"] < 0)
    anomaly_rate = anomalies / total if total > 0 else 0.0

    logger.info(
        "Validated %d records: %d anomalies (%.1f%%).",
        total,
        anomalies,
        anomaly_rate * 100,
    )

    if anomaly_rate >= 0.10:
        return {"branch": "flag_anomalies", "records": records, "anomaly_rate": anomaly_rate}
    return {"branch": "clean_data", "records": records, "anomaly_rate": anomaly_rate}


@node(cache=True)
def clean_data(data: dict) -> list[dict]:
    """Remove anomalous records (negative amounts)."""
    records = data["records"]
    cleaned = [r for r in records if r["amount"] >= 0]
    logger.info("Cleaned data: %d → %d records.", len(records), len(cleaned))
    return cleaned


@node
def flag_anomalies(data: dict) -> list[dict]:
    """Flag all records as requiring review."""
    records = data["records"]
    for r in records:
        r["flagged"] = r["amount"] < 0
    flagged_count = sum(1 for r in records if r.get("flagged"))
    logger.info("Flagged %d anomalies for review out of %d records.", flagged_count, len(records))
    return records


@node(cache=True)
def summarize(records: list[dict]) -> dict:
    """Compute summary statistics from the processed records."""
    amounts = [r["amount"] for r in records if r["amount"] >= 0]

    if not amounts:
        return {"total_records": 0, "total_revenue": 0, "avg_amount": 0, "regions": {}}

    # Per-region breakdown.
    by_region: dict[str, list[float]] = {}
    for r in records:
        if r["amount"] >= 0:
            by_region.setdefault(r["region"], []).append(r["amount"])

    summary = {
        "total_records": len(records),
        "total_revenue": round(sum(amounts), 2),
        "avg_amount": round(statistics.mean(amounts), 2),
        "median_amount": round(statistics.median(amounts), 2),
        "min_amount": round(min(amounts), 2),
        "max_amount": round(max(amounts), 2),
        "regions": {
            region: {
                "count": len(vals),
                "total": round(sum(vals), 2),
                "avg": round(statistics.mean(vals), 2),
            }
            for region, vals in sorted(by_region.items())
        },
    }
    logger.info(
        "Summary: %d records, $%.2f total revenue.",
        summary["total_records"],
        summary["total_revenue"],
    )
    return summary


@node
def report(summary: dict) -> str:
    """Generate a human-readable text report from the summary."""
    lines = [
        "=" * 50,
        "  Dagloom Demo — Sales Summary Report",
        "=" * 50,
        "",
        f"  Total Records:  {summary['total_records']}",
        f"  Total Revenue:  ${summary['total_revenue']:,.2f}",
        f"  Average Amount: ${summary['avg_amount']:,.2f}",
        f"  Median Amount:  ${summary.get('median_amount', 0):,.2f}",
        f"  Min Amount:     ${summary.get('min_amount', 0):,.2f}",
        f"  Max Amount:     ${summary.get('max_amount', 0):,.2f}",
        "",
        "  Revenue by Region:",
    ]

    for region, stats in summary.get("regions", {}).items():
        lines.append(
            f"    {region:<8} — {stats['count']:>3} sales, ${stats['total']:>10,.2f} total"
        )

    lines.extend(["", "=" * 50])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline assembly
# ---------------------------------------------------------------------------


def create_demo_pipeline(
    name: str = "demo_etl",
    schedule: str | None = None,
) -> Pipeline:
    """Create the demo ETL pipeline.

    Args:
        name: Pipeline name.
        schedule: Optional cron expression or interval shorthand.

    Returns:
        A fully assembled Pipeline.
    """
    pipeline = Pipeline(name=name, schedule=schedule)

    # Add nodes.
    pipeline.add_node(generate_data)
    pipeline.add_node(validate)
    pipeline.add_node(clean_data)
    pipeline.add_node(flag_anomalies)
    pipeline.add_node(summarize)
    pipeline.add_node(report)

    # Build DAG: generate_data >> validate >> (clean_data | flag_anomalies) >> summarize >> report
    pipeline.add_edge("generate_data", "validate")

    # Conditional branch after validate.
    from dagloom.core.node import Branch

    branch = Branch([clean_data, flag_anomalies])
    pipeline._branches["validate"] = branch
    pipeline.add_edge("validate", "clean_data")
    pipeline.add_edge("validate", "flag_anomalies")

    # Both branches merge into summarize.
    pipeline.add_edge("clean_data", "summarize")
    pipeline.add_edge("flag_anomalies", "summarize")
    pipeline.add_edge("summarize", "report")

    pipeline._tail_nodes = ["report"]

    return pipeline
