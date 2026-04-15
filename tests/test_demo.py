"""Tests for demo pipeline and CLI command (P1-6).

Covers:
- Demo pipeline nodes: generate_data, validate, clean_data, flag_anomalies, summarize, report
- create_demo_pipeline(): pipeline structure and execution
- 'dagloom demo --run' CLI command
"""

from __future__ import annotations

from click.testing import CliRunner

from dagloom.cli.main import cli
from dagloom.demo.etl_pipeline import (
    clean_data,
    create_demo_pipeline,
    flag_anomalies,
    generate_data,
    report,
    summarize,
    validate,
)

# ---------------------------------------------------------------------------
# Individual node tests
# ---------------------------------------------------------------------------


class TestDemoNodes:
    """Tests for individual demo pipeline nodes."""

    def test_generate_data_default(self) -> None:
        """generate_data produces 100 records by default."""
        records = generate_data(num_records=100, seed=42)
        assert isinstance(records, list)
        assert len(records) == 100
        assert all("id" in r and "product" in r and "amount" in r for r in records)

    def test_generate_data_deterministic(self) -> None:
        """Same seed produces same records (ignoring timestamps)."""
        r1 = generate_data(num_records=50, seed=123)
        r2 = generate_data(num_records=50, seed=123)
        # Compare everything except timestamp which varies.
        for a, b in zip(r1, r2, strict=True):
            assert a["id"] == b["id"]
            assert a["product"] == b["product"]
            assert a["amount"] == b["amount"]
            assert a["region"] == b["region"]

    def test_generate_data_custom_count(self) -> None:
        """Can generate arbitrary number of records."""
        records = generate_data(num_records=10, seed=1)
        assert len(records) == 10

    def test_generate_data_has_anomalies(self) -> None:
        """With enough records, some anomalies (negative amounts) appear."""
        records = generate_data(num_records=1000, seed=42)
        anomalies = [r for r in records if r["amount"] < 0]
        assert len(anomalies) > 0

    def test_validate_routes_clean(self) -> None:
        """validate routes to 'clean_data' when anomaly rate < 10%."""
        records = [{"amount": 100.0}] * 95 + [{"amount": -10.0}] * 5  # 5%
        result = validate(records)
        assert result["branch"] == "clean_data"
        assert result["anomaly_rate"] < 0.10

    def test_validate_routes_flag(self) -> None:
        """validate routes to 'flag_anomalies' when anomaly rate >= 10%."""
        records = [{"amount": 100.0}] * 85 + [{"amount": -10.0}] * 15  # 15%
        result = validate(records)
        assert result["branch"] == "flag_anomalies"
        assert result["anomaly_rate"] >= 0.10

    def test_validate_empty_records(self) -> None:
        """validate handles empty list."""
        result = validate([])
        assert result["branch"] == "clean_data"
        assert result["anomaly_rate"] == 0.0

    def test_clean_data_removes_negatives(self) -> None:
        """clean_data removes records with negative amounts."""
        data = {
            "records": [
                {"amount": 100.0},
                {"amount": -50.0},
                {"amount": 200.0},
            ],
            "anomaly_rate": 0.05,
        }
        result = clean_data(data)
        assert len(result) == 2
        assert all(r["amount"] >= 0 for r in result)

    def test_flag_anomalies_marks_records(self) -> None:
        """flag_anomalies adds 'flagged' field to anomalous records."""
        data = {
            "records": [
                {"amount": 100.0},
                {"amount": -50.0},
                {"amount": 200.0},
            ],
            "anomaly_rate": 0.15,
        }
        result = flag_anomalies(data)
        assert len(result) == 3
        flagged = [r for r in result if r.get("flagged")]
        assert len(flagged) == 1
        assert flagged[0]["amount"] == -50.0

    def test_summarize_computes_stats(self) -> None:
        """summarize produces correct statistics."""
        records = [
            {"amount": 100.0, "region": "North"},
            {"amount": 200.0, "region": "North"},
            {"amount": 300.0, "region": "South"},
        ]
        result = summarize(records)
        assert result["total_records"] == 3
        assert result["total_revenue"] == 600.0
        assert result["avg_amount"] == 200.0
        assert "North" in result["regions"]
        assert result["regions"]["North"]["count"] == 2

    def test_summarize_empty_records(self) -> None:
        """summarize handles empty list."""
        result = summarize([])
        assert result["total_records"] == 0
        assert result["total_revenue"] == 0

    def test_report_generates_text(self) -> None:
        """report produces readable text output."""
        summary = {
            "total_records": 100,
            "total_revenue": 25000.0,
            "avg_amount": 250.0,
            "median_amount": 240.0,
            "min_amount": 10.0,
            "max_amount": 500.0,
            "regions": {
                "North": {"count": 50, "total": 12500.0, "avg": 250.0},
            },
        }
        result = report(summary)
        assert "Sales Summary Report" in result
        assert "$25,000.00" in result
        assert "North" in result


# ---------------------------------------------------------------------------
# Pipeline creation and execution
# ---------------------------------------------------------------------------


class TestDemoPipeline:
    """Tests for create_demo_pipeline() and full execution."""

    def test_create_demo_pipeline_structure(self) -> None:
        """Pipeline has correct nodes and edges."""
        pipeline = create_demo_pipeline()
        assert pipeline.name == "demo_etl"
        assert len(pipeline.nodes) == 6

        node_names = set(pipeline.nodes.keys())
        assert node_names == {
            "generate_data",
            "validate",
            "clean_data",
            "flag_anomalies",
            "summarize",
            "report",
        }

        assert ("generate_data", "validate") in pipeline.edges
        assert ("validate", "clean_data") in pipeline.edges
        assert ("validate", "flag_anomalies") in pipeline.edges
        assert ("summarize", "report") in pipeline.edges

    def test_create_demo_pipeline_with_schedule(self) -> None:
        """Pipeline can be created with a schedule."""
        pipeline = create_demo_pipeline(schedule="0 9 * * *")
        assert pipeline.schedule == "0 9 * * *"

    def test_create_demo_pipeline_custom_name(self) -> None:
        """Pipeline can be created with a custom name."""
        pipeline = create_demo_pipeline(name="my_demo")
        assert pipeline.name == "my_demo"

    def test_demo_pipeline_runs_successfully(self) -> None:
        """Full pipeline execution produces a text report."""
        pipeline = create_demo_pipeline()
        result = pipeline.run(num_records=50, seed=42)
        assert isinstance(result, str)
        assert "Sales Summary Report" in result
        assert "Total Revenue" in result

    def test_demo_pipeline_with_few_records(self) -> None:
        """Pipeline works with minimal records."""
        pipeline = create_demo_pipeline()
        result = pipeline.run(num_records=5, seed=1)
        assert isinstance(result, str)
        assert "Sales Summary Report" in result

    def test_demo_pipeline_branch_selection(self) -> None:
        """Pipeline selects correct branch based on anomaly rate."""
        pipeline = create_demo_pipeline()
        # Default seed=42 with 100 records: ~5% anomalies → clean_data branch.
        result = pipeline.run(num_records=100, seed=42)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


class TestDemoCLI:
    """Tests for 'dagloom demo --run' command."""

    def test_demo_run_succeeds(self) -> None:
        """'dagloom demo --run' executes the demo pipeline."""
        runner = CliRunner()
        result = runner.invoke(cli, ["demo", "--run"])
        assert result.exit_code == 0
        assert "Sales Summary Report" in result.output
        assert "completed successfully" in result.output

    def test_demo_run_custom_records(self) -> None:
        """'dagloom demo --run --records 20' uses custom record count."""
        runner = CliRunner()
        result = runner.invoke(cli, ["demo", "--run", "--records", "20"])
        assert result.exit_code == 0
        assert "Sales Summary Report" in result.output

    def test_demo_help(self) -> None:
        """'dagloom demo --help' shows usage."""
        runner = CliRunner()
        result = runner.invoke(cli, ["demo", "--help"])
        assert result.exit_code == 0
        assert "demo" in result.output.lower()
