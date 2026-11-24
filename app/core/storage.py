"""Object Storage (MinIO) client for HirePulse.

Handles thread-scoped file persistence in a dedicated MinIO Docker container,
replacing local filesystem directory storage.
"""

import io
import logging
from typing import BinaryIO, List, Optional, Union

from minio import Minio
from minio.error import S3Error

from app.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)

logger = logging.getLogger(__name__)


class StorageService:
    """Encapsulates MinIO S3 object storage operations."""

    def __init__(self):
        # Clean endpoint (remove http:// or https:// if provided)
        endpoint = MINIO_ENDPOINT
        if endpoint.startswith("http://"):
            endpoint = endpoint[7:]
        elif endpoint.startswith("https://"):
            endpoint = endpoint[8:]

        self.endpoint = endpoint
        self.bucket = MINIO_BUCKET
        self.client = Minio(
            endpoint=self.endpoint,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        self.ensure_bucket()

    def ensure_bucket(self, bucket_name: Optional[str] = None) -> None:
        """Create the target bucket if it does not already exist."""
        target = bucket_name or self.bucket
        try:
            if not self.client.bucket_exists(target):
                self.client.make_bucket(target)
                logger.info("Created MinIO bucket '%s'", target)
        except Exception as e:
            logger.warning("Could not verify or create MinIO bucket '%s': %s", target, e)

    def upload_file(
        self,
        data: Union[bytes, BinaryIO],
        object_name: str,
        content_type: str = "application/octet-stream",
        length: int = -1,
    ) -> str:
        """Upload a file or byte stream to MinIO.
        
        Args:
            data: Raw file bytes or file-like binary stream.
            object_name: Key path (e.g. '{thread_id}/{filename}').
            content_type: MIME type.
            length: Stream size in bytes (-1 for auto-calculation on bytes).
            
        Returns:
            The object key name in MinIO.
        """
        if isinstance(data, (bytes, bytearray)):
            stream = io.BytesIO(data)
            stream_length = len(data)
        else:
            stream = data
            stream_length = length

        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=stream,
            length=stream_length,
            part_size=10 * 1024 * 1024 if stream_length < 0 else 0,
            content_type=content_type,
        )
        logger.info("Uploaded object '%s' to bucket '%s'", object_name, self.bucket)
        return object_name

    def download_file(self, object_name: str) -> bytes:
        """Download and return the content of an object as bytes."""
        response = self.client.get_object(self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def list_thread_files(self, thread_id: str) -> List[str]:
        """List filenames uploaded for a specific thread_id."""
        prefix = f"{thread_id}/"
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        filenames = []
        for obj in objects:
            # Strip thread_id/ prefix to return bare filename
            name = obj.object_name[len(prefix):]
            if name:
                filenames.append(name)
        return filenames

    def delete_file(self, object_name: str) -> bool:
        """Delete a single object from MinIO."""
        try:
            self.client.remove_object(self.bucket, object_name)
            return True
        except Exception as e:
            logger.error("Failed to delete '%s' from MinIO: %s", object_name, e)
            return False

    def delete_thread_files(self, thread_id: str) -> int:
        """Delete all files associated with a given thread."""
        prefix = f"{thread_id}/"
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        count = 0
        for obj in objects:
            try:
                self.client.remove_object(self.bucket, obj.object_name)
                count += 1
            except Exception as e:
                logger.error("Error deleting %s: %s", obj.object_name, e)
        return count


# Singleton storage instance
storage = StorageService()
