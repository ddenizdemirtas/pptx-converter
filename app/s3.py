"""S3 client wrapper for download and upload operations."""

import os
from pathlib import Path

import boto3
from botocore.config import Config
import structlog

from app.config import settings

logger = structlog.get_logger()


class S3Client:
    """Wrapper around boto3 S3 client for converter operations."""

    def __init__(self) -> None:
        """Initialize S3 client with configured settings."""
        client_config = Config(
            region_name=settings.aws_region,
            retries={"max_attempts": 3, "mode": "standard"},
        )

        # Build client kwargs
        client_kwargs: dict = {"config": client_config}

        if settings.s3_endpoint_url:
            client_kwargs["endpoint_url"] = settings.s3_endpoint_url

        # Only use explicit credentials if S3_ACCESS_KEY_ID is set (local dev)
        # On Lambda, these are None and boto3 uses the execution role automatically
        if settings.s3_access_key_id and settings.s3_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.s3_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.s3_secret_access_key

        self._client = boto3.client("s3", **client_kwargs)

    def download_file(self, bucket: str, key: str, local_path: Path) -> None:
        """
        Download a file from S3 to local filesystem.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            local_path: Local file path to write to
        """
        logger.info("Downloading file from S3", bucket=bucket,
                    key=key, local_path=str(local_path))

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        self._client.download_file(bucket, key, str(local_path))

        logger.info(
            "Download complete",
            bucket=bucket,
            key=key,
            size_bytes=local_path.stat().st_size,
        )

    def upload_file(self, local_path: Path, bucket: str, key: str) -> None:
        """
        Upload a local file to S3.

        Args:
            local_path: Local file path to upload
            bucket: S3 bucket name
            key: S3 object key
        """
        logger.info("Uploading file to S3", local_path=str(
            local_path), bucket=bucket, key=key)

        self._client.upload_file(str(local_path), bucket, key)

        logger.info(
            "Upload complete",
            bucket=bucket,
            key=key,
            size_bytes=local_path.stat().st_size,
        )

    def upload_json(self, data: str, bucket: str, key: str) -> None:
        """
        Upload JSON string directly to S3.

        Args:
            data: JSON string to upload
            bucket: S3 bucket name
            key: S3 object key
        """
        logger.info("Uploading JSON to S3", bucket=bucket, key=key)

        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data.encode("utf-8"),
            ContentType="application/json",
        )

        logger.info("JSON upload complete", bucket=bucket, key=key)

    def check_object_exists(self, bucket: str, key: str) -> bool:
        """
        Check if an object exists in S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            True if object exists, False otherwise
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except self._client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def get_object_size(self, bucket: str, key: str) -> int:
        """
        Get the size of an S3 object in bytes.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            Size in bytes
        """
        response = self._client.head_object(Bucket=bucket, Key=key)
        return response["ContentLength"]


# Global S3 client instance
s3_client = S3Client()
