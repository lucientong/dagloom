"""Node output caching.

Caches node outputs based on a SHA-256 hash of the serialized input
arguments.  Supports pickle, JSON, and (placeholder) parquet formats.

Example::

    cache = CacheManager(db, cache_dir=".dagloom/cache")
    hit = await cache.get("clean", input_hash)
    if hit is None:
        result = node(data)
        await cache.put("clean", input_hash, result)
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
from pathlib import Path
from typing import Any

from dagloom.store.db import Database

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = ".dagloom/cache"


def compute_input_hash(*args: Any, **kwargs: Any) -> str:
    """Compute a deterministic SHA-256 hash for the given arguments.

    Uses pickle serialization to handle arbitrary Python objects.
    Falls back to repr() for unpicklable objects.

    Returns:
        A hex-encoded SHA-256 digest.
    """
    hasher = hashlib.sha256()
    for arg in args:
        try:
            hasher.update(pickle.dumps(arg))
        except (pickle.PicklingError, TypeError):
            hasher.update(repr(arg).encode())
    for key in sorted(kwargs.keys()):
        hasher.update(key.encode())
        try:
            hasher.update(pickle.dumps(kwargs[key]))
        except (pickle.PicklingError, TypeError):
            hasher.update(repr(kwargs[key]).encode())
    return hasher.hexdigest()


class CacheManager:
    """Manage cached node outputs.

    Args:
        db: Database instance for cache metadata.
        cache_dir: Directory to store cached output files.
    """

    def __init__(
        self,
        db: Database,
        cache_dir: str | Path = _DEFAULT_CACHE_DIR,
    ) -> None:
        self.db = db
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def get(
        self,
        node_id: str,
        input_hash: str,
    ) -> Any | None:
        """Retrieve a cached output if it exists.

        Args:
            node_id: The node whose output to look up.
            input_hash: The SHA-256 hash of the node's input.

        Returns:
            The cached output value, or None if not cached.
        """
        entry = await self.db.get_cache_entry(node_id, input_hash)
        if entry is None:
            return None

        output_path = Path(entry["output_path"])
        if not output_path.exists():
            # File was deleted; clean up metadata.
            await self.db.delete_cache_entry(node_id, input_hash)
            return None

        fmt = entry.get("serialization_format", "pickle")
        return self._deserialize(output_path, fmt)

    async def put(
        self,
        node_id: str,
        input_hash: str,
        value: Any,
        fmt: str = "pickle",
    ) -> str:
        """Cache a node output.

        Args:
            node_id: The node that produced the output.
            input_hash: The SHA-256 hash of the input.
            value: The output value to cache.
            fmt: Serialization format ("pickle" or "json").

        Returns:
            The path to the cached file.
        """
        node_dir = self.cache_dir / node_id
        node_dir.mkdir(parents=True, exist_ok=True)

        ext = ".pkl" if fmt == "pickle" else ".json"
        output_path = node_dir / f"{input_hash}{ext}"

        self._serialize(value, output_path, fmt)
        size_bytes = output_path.stat().st_size

        await self.db.save_cache_entry(
            node_id=node_id,
            input_hash=input_hash,
            output_path=str(output_path),
            serialization_format=fmt,
            size_bytes=size_bytes,
        )
        logger.debug(
            "Cached output for %s (hash=%s, size=%d bytes).",
            node_id,
            input_hash[:12],
            size_bytes,
        )
        return str(output_path)

    async def invalidate(self, node_id: str, input_hash: str) -> None:
        """Remove a cache entry and its file.

        Args:
            node_id: The node whose cache to invalidate.
            input_hash: The specific input hash to remove.
        """
        entry = await self.db.get_cache_entry(node_id, input_hash)
        if entry:
            path = Path(entry["output_path"])
            if path.exists():
                path.unlink()
            await self.db.delete_cache_entry(node_id, input_hash)

    # -- Serialization helpers ------------------------------------------------

    @staticmethod
    def _serialize(value: Any, path: Path, fmt: str) -> None:
        """Serialize a value to disk."""
        if fmt == "json":
            path.write_text(json.dumps(value, default=str), encoding="utf-8")
        else:  # pickle
            path.write_bytes(pickle.dumps(value))

    @staticmethod
    def _deserialize(path: Path, fmt: str) -> Any:
        """Deserialize a value from disk."""
        if fmt == "json":
            return json.loads(path.read_text(encoding="utf-8"))
        else:  # pickle
            return pickle.loads(path.read_bytes())  # noqa: S301
