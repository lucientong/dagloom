"""S3 / MinIO connector using aiobotocore.

Requires the ``connectors`` extra: ``pip install dagloom[connectors]``

Example::

    config = ConnectionConfig(host="s3.amazonaws.com", extra={"region": "us-east-1", "aws_access_key_id": "...", "aws_secret_access_key": "..."})
    async with S3Connector(config) as s3:
        data = await s3.execute("get", bucket="my-bucket", key="data/file.csv")
"""

from __future__ import annotations

import logging
from typing import Any

from dagloom.connectors.base import BaseConnector, ConnectionConfig

logger = logging.getLogger(__name__)


class S3Connector(BaseConnector):
    """S3 / MinIO async connector using aiobotocore.

    Args:
        config: Connection configuration. Use ``extra`` dict for AWS credentials
                and region: ``{"region": "us-east-1", "aws_access_key_id": "...", ...}``
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._session: Any = None
        self._client: Any = None

    async def connect(self) -> None:
        """Create an aiobotocore S3 client."""
        try:
            from aiobotocore.session import get_session  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "aiobotocore is required for S3Connector. "
                "Install it with: pip install dagloom[connectors]"
            ) from exc

        self._session = get_session()
        extra = self.config.extra
        endpoint_url = f"https://{self.config.host}" if self.config.host != "localhost" else f"http://{self.config.host}:{self.config.port or 9000}"

        self._client = self._session.create_client(
            "s3",
            endpoint_url=endpoint_url if self.config.host else None,
            region_name=extra.get("region", "us-east-1"),
            aws_access_key_id=extra.get("aws_access_key_id", self.config.username),
            aws_secret_access_key=extra.get("aws_secret_access_key", self.config.password),
        )
        self._client = await self._client.__aenter__()
        self._connected = True
        logger.info("S3 connected: %s", self.config.host or "default")

    async def disconnect(self) -> None:
        """Close the S3 client."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
        self._session = None
        self._connected = False
        logger.info("S3 disconnected.")

    async def health_check(self) -> bool:
        """List buckets to check connectivity."""
        if not self._client:
            return False
        try:
            await self._client.list_buckets()
            return True
        except Exception:
            return False

    async def execute(self, operation: str, **kwargs: Any) -> Any:
        """Execute an S3 operation.

        Args:
            operation: One of "get", "put", "delete", "list".
            **kwargs: Operation-specific parameters:
                - bucket: Bucket name (required).
                - key: Object key (required for get/put/delete).
                - body: Object body (required for put).

        Returns:
            Operation result (bytes for get, dict for others).
        """
        if not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        bucket = kwargs.get("bucket", self.config.database)
        key = kwargs.get("key", "")

        if operation == "get":
            resp = await self._client.get_object(Bucket=bucket, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()

        elif operation == "put":
            body = kwargs.get("body", b"")
            return await self._client.put_object(Bucket=bucket, Key=key, Body=body)

        elif operation == "delete":
            return await self._client.delete_object(Bucket=bucket, Key=key)

        elif operation == "list":
            prefix = kwargs.get("prefix", "")
            resp = await self._client.list_objects_v2(Bucket=bucket, Prefix=prefix)
            return resp.get("Contents", [])

        else:
            raise ValueError(f"Unknown S3 operation: {operation!r}")
