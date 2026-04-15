"""MongoDB connector using motor (async driver).

Requires the ``mongodb`` extra: ``pip install dagloom[mongodb]``

Example::

    config = ConnectionConfig(
        host="localhost", port=27017, database="mydb",
        username="user", password="pass"
    )
    async with MongoDBConnector(config) as mongo:
        docs = await mongo.execute("find", collection="users", filter={"active": True})
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class MongoDBConnector(BaseConnector):
    """MongoDB async connector using motor.

    Args:
        config: Connection configuration (host, port, database, credentials).
    """

    def __init__(self, config: ConnectionConfig) -> None:
        if config.port == 0:
            config.port = 27017
        super().__init__(config)
        self._client: Any = None
        self._db: Any = None

    async def connect(self) -> None:
        """Create a motor async client and select the database."""
        try:
            from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "motor is required for MongoDBConnector. "
                "Install it with: pip install dagloom[mongodb]"
            ) from exc

        # Build connection URI.
        auth = ""
        if self.config.username and self.config.password:
            auth = f"{self.config.username}:{self.config.password}@"

        scheme = "mongodb+srv" if self.config.extra.get("srv", False) else "mongodb"
        uri = f"{scheme}://{auth}{self.config.host}:{self.config.port}"

        self._client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=int(self.config.timeout * 1000),
            maxPoolSize=self.config.pool_size,
            tls=self.config.ssl,
        )
        self._db = self._client[self.config.database]
        self._connected = True
        logger.info(
            "MongoDB connected: %s:%d/%s",
            self.config.host,
            self.config.port,
            self.config.database,
        )

    async def disconnect(self) -> None:
        """Close the motor client."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
        self._connected = False
        logger.info("MongoDB disconnected.")

    async def health_check(self) -> bool:
        """Ping the server to check connectivity."""
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False

    async def execute(self, operation: str, **kwargs: Any) -> Any:
        """Execute a MongoDB operation.

        Args:
            operation: Operation name — one of ``find``, ``find_one``,
                ``insert_one``, ``insert_many``, ``update_one``, ``update_many``,
                ``delete_one``, ``delete_many``, ``aggregate``, ``count``.
            **kwargs:
                - collection (str): Collection name (required).
                - filter (dict): Query filter for find/update/delete operations.
                - document (dict): Document for insert_one.
                - documents (list[dict]): Documents for insert_many.
                - update (dict): Update spec for update operations.
                - pipeline (list[dict]): Aggregation pipeline stages.

        Returns:
            Operation result (list of documents, insert result, etc.).

        Raises:
            ConnectionError: If not connected.
            ValueError: If operation is unknown or collection is missing.
        """
        if not self._db:
            raise ConnectionError("Not connected. Call connect() first.")

        collection_name = kwargs.pop("collection", None)
        if not collection_name:
            raise ValueError("'collection' is required for MongoDB operations.")

        coll = self._db[collection_name]

        if operation == "find":
            cursor = coll.find(kwargs.get("filter", {}))
            return await cursor.to_list(length=kwargs.get("limit", 100))

        if operation == "find_one":
            return await coll.find_one(kwargs.get("filter", {}))

        if operation == "insert_one":
            result = await coll.insert_one(kwargs.get("document", {}))
            return {"inserted_id": str(result.inserted_id)}

        if operation == "insert_many":
            result = await coll.insert_many(kwargs.get("documents", []))
            return {"inserted_ids": [str(i) for i in result.inserted_ids]}

        if operation == "update_one":
            result = await coll.update_one(kwargs.get("filter", {}), kwargs.get("update", {}))
            return {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
            }

        if operation == "update_many":
            result = await coll.update_many(kwargs.get("filter", {}), kwargs.get("update", {}))
            return {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
            }

        if operation == "delete_one":
            result = await coll.delete_one(kwargs.get("filter", {}))
            return {"deleted_count": result.deleted_count}

        if operation == "delete_many":
            result = await coll.delete_many(kwargs.get("filter", {}))
            return {"deleted_count": result.deleted_count}

        if operation == "aggregate":
            cursor = coll.aggregate(kwargs.get("pipeline", []))
            return await cursor.to_list(length=kwargs.get("limit", 100))

        if operation == "count":
            return await coll.count_documents(kwargs.get("filter", {}))

        raise ValueError(f"Unknown MongoDB operation: {operation!r}")
