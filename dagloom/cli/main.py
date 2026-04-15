"""Dagloom CLI — Command line interface.

Provides commands to serve the web UI, run pipelines, list pipelines,
inspect DAG structures, and show version info.

Usage::

    dagloom serve          # Start web server
    dagloom run <file>     # Run a pipeline from a Python file
    dagloom list           # List registered pipelines
    dagloom inspect <file> # Show DAG structure
    dagloom version        # Show version info
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import click

import dagloom


@click.group()
def cli() -> None:
    """Dagloom — A lightweight pipeline/workflow engine."""


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host.")
@click.option("--port", default=8000, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev mode).")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the Dagloom web server."""
    import uvicorn

    click.echo(f"🧶 Dagloom server starting on http://{host}:{port}")
    uvicorn.run(
        "dagloom.server.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--pipeline-var", default="pipeline", help="Pipeline variable name in the file.")
@click.option(
    "--input",
    "-i",
    "inputs",
    multiple=True,
    help='Input key=value pairs, e.g. -i url="https://...".',
)
def run(file: str, pipeline_var: str, inputs: tuple[str, ...]) -> None:
    """Run a pipeline defined in a Python file."""
    # Parse inputs.
    kwargs: dict[str, Any] = {}
    for item in inputs:
        if "=" not in item:
            click.echo(f"Invalid input format: {item!r} (expected key=value)", err=True)
            sys.exit(1)
        key, value = item.split("=", 1)
        # Try to parse as JSON, fall back to string.
        try:
            kwargs[key] = json.loads(value)
        except json.JSONDecodeError:
            kwargs[key] = value

    # Load the pipeline from file.
    pipeline = _load_pipeline_from_file(file, pipeline_var)
    if pipeline is None:
        click.echo(
            f"Could not find variable {pipeline_var!r} in {file!r}.",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Running pipeline from {file} ...")
    try:
        result = pipeline.run(**kwargs)
        click.echo("✅ Pipeline completed successfully.")
        click.echo(f"Result: {result}")
    except Exception as exc:
        click.echo(f"❌ Pipeline failed: {exc}", err=True)
        sys.exit(1)


@cli.command("list")
def list_cmd() -> None:
    """List registered pipelines (from database)."""
    import asyncio

    from dagloom.store.db import Database

    async def _list() -> list[dict[str, Any]]:
        db = Database()
        await db.connect()
        pipelines = await db.list_pipelines()
        await db.close()
        return pipelines

    pipelines = asyncio.run(_list())
    if not pipelines:
        click.echo("No pipelines registered yet.")
        click.echo("Run a pipeline first, or use the web UI to create one.")
        return

    click.echo(f"{'Name':<30} {'ID':<15} {'Updated':<25}")
    click.echo("-" * 70)
    for p in pipelines:
        click.echo(f"{p['name']:<30} {p['id']:<15} {p.get('updated_at', ''):<25}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--pipeline-var", default="pipeline", help="Pipeline variable name.")
def inspect(file: str, pipeline_var: str) -> None:
    """Inspect and display the DAG structure of a pipeline."""
    pipeline = _load_pipeline_from_file(file, pipeline_var)
    if pipeline is None:
        click.echo(
            f"Could not find variable {pipeline_var!r} in {file!r}.",
            err=True,
        )
        sys.exit(1)

    click.echo(pipeline.visualize())
    click.echo(f"\nTotal nodes: {len(pipeline)}")
    click.echo(f"Total edges: {len(pipeline.edges)}")
    click.echo(f"Root nodes:  {', '.join(pipeline.root_nodes())}")
    click.echo(f"Leaf nodes:  {', '.join(pipeline.leaf_nodes())}")


@cli.command()
def version() -> None:
    """Show Dagloom version information."""
    click.echo(f"dagloom {dagloom.__version__}")
    click.echo(f"Python {sys.version}")


@cli.command()
@click.option(
    "--run",
    "run_only",
    is_flag=True,
    help="Run the demo pipeline directly (no server).",
)
@click.option("--host", default="127.0.0.1", help="Bind host (server mode).")
@click.option("--port", default=8000, type=int, help="Bind port (server mode).")
@click.option("--records", default=100, type=int, help="Number of demo records to generate.")
def demo(run_only: bool, host: str, port: int, records: int) -> None:
    """Run the built-in demo ETL pipeline.

    Without --run, starts the web server with the demo pipeline registered.
    With --run, executes the pipeline directly and prints the report.
    """
    from dagloom.demo import create_demo_pipeline

    pipeline = create_demo_pipeline(name="demo_etl")

    if run_only:
        click.echo("Running demo ETL pipeline ...")
        try:
            result = pipeline.run(num_records=records)
            click.echo(result)
            click.echo("\n✅ Demo pipeline completed successfully.")
        except Exception as exc:
            click.echo(f"❌ Demo pipeline failed: {exc}", err=True)
            sys.exit(1)
        return

    # Server mode: register the pipeline and start serving.
    import asyncio
    import tempfile

    import uvicorn

    from dagloom.store.db import Database

    async def _setup_and_serve() -> None:
        tmpdir = tempfile.mkdtemp(prefix="dagloom-demo-")
        db_path = Path(tmpdir) / "demo.db"

        db = Database(db_path)
        await db.connect()
        await db.save_pipeline(
            pipeline_id="demo_etl",
            name="demo_etl",
            description="Built-in demo ETL pipeline",
            node_names=list(pipeline.nodes.keys()),
            edges=pipeline.edges,
        )
        await db.close()

        click.echo(f"Demo database: {db_path}")
        click.echo(f"Starting Dagloom demo server on http://{host}:{port}")
        click.echo("Press Ctrl+C to stop.\n")

        config = uvicorn.Config(
            "dagloom.server.app:create_app",
            host=host,
            port=port,
            factory=True,
        )
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(_setup_and_serve())


# -- Scheduler commands -------------------------------------------------------


@cli.group()
def scheduler() -> None:
    """Manage the built-in pipeline scheduler."""


@scheduler.command("list")
def scheduler_list() -> None:
    """List all scheduled pipelines."""
    import asyncio

    from dagloom.store.db import Database

    async def _list() -> list[dict[str, Any]]:
        db = Database()
        await db.connect()
        schedules = await db.list_schedules()
        await db.close()
        return schedules

    schedules = asyncio.run(_list())
    if not schedules:
        click.echo("No schedules registered.")
        return

    click.echo(f"{'ID':<15} {'Pipeline':<20} {'Schedule':<20} {'Enabled':<10} {'Last Run':<25}")
    click.echo("-" * 90)
    for s in schedules:
        enabled = "Yes" if s.get("enabled") else "No"
        click.echo(
            f"{s['id']:<15} {s['pipeline_id']:<20} {s['cron_expr']:<20} "
            f"{enabled:<10} {s.get('last_run', 'Never'):<25}"
        )


@scheduler.command("status")
def scheduler_status() -> None:
    """Show scheduler status."""
    import asyncio

    from dagloom.store.db import Database

    async def _status() -> int:
        db = Database()
        await db.connect()
        schedules = await db.list_schedules()
        await db.close()
        return len(schedules)

    count = asyncio.run(_status())
    click.echo(f"Registered schedules: {count}")
    click.echo("Note: The scheduler runs in-process with 'dagloom serve'.")


# -- Secret commands ----------------------------------------------------------


@cli.group()
def secret() -> None:
    """Manage encrypted secrets."""


@secret.command("set")
@click.argument("key")
@click.argument("value")
def secret_set(key: str, value: str) -> None:
    """Store an encrypted secret."""
    import asyncio

    from dagloom.security.encryption import Encryptor
    from dagloom.store.db import Database

    async def _set() -> None:
        db = Database()
        await db.connect()
        encryptor = Encryptor()
        encrypted = encryptor.encrypt(value)
        await db.save_secret(key, encrypted)
        await db.close()

    asyncio.run(_set())
    click.echo(f"Secret {key!r} saved.")


@secret.command("get")
@click.argument("key")
def secret_get(key: str) -> None:
    """Retrieve a secret value."""
    import asyncio

    from dagloom.security.encryption import Encryptor
    from dagloom.store.db import Database

    async def _get() -> str | None:
        db = Database()
        await db.connect()
        row = await db.get_secret(key)
        await db.close()
        if row is None:
            return None
        encryptor = Encryptor()
        return encryptor.decrypt(row["encrypted_value"])

    result = asyncio.run(_get())
    if result is None:
        click.echo(f"Secret {key!r} not found.", err=True)
        sys.exit(1)
    click.echo(result)


@secret.command("list")
def secret_list() -> None:
    """List all secret key names."""
    import asyncio

    from dagloom.store.db import Database

    async def _list() -> list[dict[str, Any]]:
        db = Database()
        await db.connect()
        secrets = await db.list_secrets()
        await db.close()
        return secrets

    secrets = asyncio.run(_list())
    if not secrets:
        click.echo("No secrets stored.")
        return

    click.echo(f"{'Key':<30} {'Created':<25} {'Updated':<25}")
    click.echo("-" * 80)
    for s in secrets:
        click.echo(f"{s['key']:<30} {s.get('created_at', ''):<25} {s.get('updated_at', ''):<25}")


@secret.command("delete")
@click.argument("key")
def secret_delete(key: str) -> None:
    """Delete a secret."""
    import asyncio

    from dagloom.store.db import Database

    async def _delete() -> bool:
        db = Database()
        await db.connect()
        existing = await db.get_secret(key)
        if existing is None:
            await db.close()
            return False
        await db.delete_secret(key)
        await db.close()
        return True

    deleted = asyncio.run(_delete())
    if not deleted:
        click.echo(f"Secret {key!r} not found.", err=True)
        sys.exit(1)
    click.echo(f"Secret {key!r} deleted.")


# -- Helpers ------------------------------------------------------------------


def _load_pipeline_from_file(file_path: str, var_name: str) -> Any | None:
    """Dynamically load a Pipeline object from a Python file.

    Args:
        file_path: Path to the Python file.
        var_name: Name of the Pipeline variable to look for.

    Returns:
        The Pipeline object, or None if not found.
    """
    path = Path(file_path).resolve()
    spec = importlib.util.spec_from_file_location("_user_pipeline", str(path))
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules["_user_pipeline"] = module
    spec.loader.exec_module(module)

    pipeline = getattr(module, var_name, None)
    return pipeline
