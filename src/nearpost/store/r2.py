"""Cloudflare R2 through its S3-compatible API."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from nearpost.store.base import Blob, PreconditionFailedError, validate_key

# 412 when a condition fails; R2 answers 409 when two conditional writes race.
_LOST_CONDITION = frozenset({"PreconditionFailed", "ConditionalRequestConflict"})


def make_client(*, account_id: str, access_key_id: str, secret_access_key: str) -> Any:
    return boto3.client(
        service_name="s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


class R2Store:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def get(self, key: str) -> Blob | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=validate_key(key))
        except ClientError as error:
            if _code(error) in ("NoSuchKey", "404"):
                return None
            raise
        return Blob(response["Body"].read(), response["ETag"].strip('"'))

    def put(
        self,
        key: str,
        data: bytes,
        *,
        if_none_match: bool = False,
        if_match: str | None = None,
        content_type: str = "application/json",
    ) -> str:
        request: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": validate_key(key),
            "Body": data,
            "ContentType": content_type,
        }
        if if_none_match:
            request["IfNoneMatch"] = "*"
        if if_match is not None:
            request["IfMatch"] = f'"{if_match}"'
        try:
            response = self._client.put_object(**request)
        except ClientError as error:
            if _code(error) in _LOST_CONDITION:
                raise PreconditionFailedError(key) from error
            raise
        return response["ETag"].strip('"')

    def list_keys(self, prefix: str, start_after: str | None = None) -> list[str]:
        request: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
        if start_after is not None:
            request["StartAfter"] = start_after
        keys: list[str] = []
        while True:
            response = self._client.list_objects_v2(**request)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                return keys
            request["ContinuationToken"] = response["NextContinuationToken"]
