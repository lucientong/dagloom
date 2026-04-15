"""File system watcher for bidirectional code <-> UI sync.

Monitors Python pipeline files for changes and broadcasts DAG updates
via WebSocket.  Uses ``watchfiles`` (already installed as a uvicorn
dependency) for async, cross-platform file watching.

Example::

    watcher = PipelineWatcher(
        watch_dirs=["/path/to/pipelines"],
        on_change=my_callback,
    )
    await watcher.start()
    # ... later ...
    await watcher.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PipelineWatcher:
    """Watch pipeline directories for file changes and trigger re-parse.

    Args:
        watch_dirs: Directories to monitor for ``.py`` file changes.
        on_change: Async callback invoked when a file changes.
            Signature: ``async (file_path: str, dag: dict) -> None``
        debounce_ms: Minimum interval between processing changes
            for the same file (default 500ms).
    """

    def __init__(
        self,
        watch_dirs: list[str | Path],
        on_change: Any = None,
        debounce_ms: int = 500,
    ) -> None:
        self.watch_dirs = [Path(d) for d in watch_dirs]
        self.on_change = on_change
        self.debounce_ms = debounce_ms
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # Track file hashes to detect actual content changes.
        self._file_hashes: dict[str, str] = {}

    @property
    def running(self) -> bool:
        """Whether the watcher is currently active."""
        return self._running

    async def start(self) -> None:
        """Start watching for file changes in background."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info(
            "Pipeline watcher started for: %s",
            [str(d) for d in self.watch_dirs],
        )

    async def stop(self) -> None:
        """Stop the file watcher."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._file_hashes.clear()
        logger.info("Pipeline watcher stopped.")

    async def _watch_loop(self) -> None:
        """Main watch loop using watchfiles."""
        try:
            from watchfiles import Change, awatch
        except ImportError:
            logger.warning(
                "watchfiles not installed. File watcher disabled. "
                "Install with: pip install watchfiles"
            )
            return

        watch_paths = [str(d) for d in self.watch_dirs if d.exists()]
        if not watch_paths:
            logger.warning("No valid watch directories found.")
            return

        try:
            async for changes in awatch(
                *watch_paths,
                step=self.debounce_ms,
                rust_timeout=5000,
            ):
                if not self._running:
                    break

                for change_type, file_path in changes:
                    if not file_path.endswith(".py"):
                        continue
                    if change_type == Change.deleted:
                        self._file_hashes.pop(file_path, None)
                        continue

                    await self._process_change(file_path)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Pipeline watcher error.")

    async def _process_change(self, file_path: str) -> None:
        """Process a single file change event."""
        from dagloom.server.codegen import code_to_dag, compute_source_hash

        path = Path(file_path)
        if not path.exists():
            return

        try:
            source = path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Failed to read %s", file_path)
            return

        # Check if content actually changed (avoid spurious events).
        new_hash = compute_source_hash(source)
        old_hash = self._file_hashes.get(file_path)
        if new_hash == old_hash:
            return
        self._file_hashes[file_path] = new_hash

        try:
            dag = code_to_dag(source)
            dag["source_hash"] = new_hash
            dag["source_file"] = file_path
        except SyntaxError:
            logger.warning("Syntax error in %s, skipping.", file_path)
            return
        except Exception:
            logger.warning("Failed to parse %s", file_path, exc_info=True)
            return

        logger.info("File changed: %s — re-parsed DAG.", file_path)

        if self.on_change is not None:
            try:
                await self.on_change(file_path, dag)
            except Exception:
                logger.warning(
                    "on_change callback failed for %s",
                    file_path,
                    exc_info=True,
                )

    def update_hash(self, file_path: str, source_hash: str) -> None:
        """Update the tracked hash for a file (after writing from UI).

        This prevents the watcher from re-triggering when we write
        the file ourselves.
        """
        self._file_hashes[file_path] = source_hash
