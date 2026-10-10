"""Lager-abstraktion: samme kode skriver til ADLS Gen2 i Azure og til en mappe lokalt.

I Azure bruges managed identity (DefaultAzureCredential), så der ligger ingen
nøgler eller connection strings i koden eller i app settings.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd


class LocalStore:
    def __init__(self, root: str):
        self.root = Path(root)

    def read(self, container: str, path: str) -> bytes | None:
        target = self.root / container / path
        return target.read_bytes() if target.exists() else None

    def write(self, container: str, path: str, data: bytes, content_type: str = "application/octet-stream",
              cache_control: str | None = None) -> str:
        target = self.root / container / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)


class BlobStore:
    """Virker både mod ADLS Gen2 (hierarkisk navnerum) og almindelig Blob Storage."""

    def __init__(self, account_url: str):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        self.account_url = account_url.rstrip("/")
        self.client = BlobServiceClient(account_url=self.account_url, credential=DefaultAzureCredential())

    def read(self, container: str, path: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.client.get_blob_client(container, path).download_blob().readall()
        except ResourceNotFoundError:
            return None

    def write(self, container: str, path: str, data: bytes, content_type: str = "application/octet-stream",
              cache_control: str | None = None) -> str:
        from azure.storage.blob import ContentSettings

        self.client.get_blob_client(container, path).upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type, cache_control=cache_control),
        )
        return f"{self.account_url}/{container}/{path}"


# Hjælpere til de formater, pipelinen bruger


def read_parquet(store, container: str, path: str) -> pd.DataFrame | None:
    raw = store.read(container, path)
    return pd.read_parquet(io.BytesIO(raw)) if raw else None


def write_parquet(store, container: str, path: str, df: pd.DataFrame) -> str:
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    return store.write(container, path, buffer.getvalue(), "application/vnd.apache.parquet")


def read_json(store, container: str, path: str) -> dict | None:
    raw = store.read(container, path)
    return json.loads(raw) if raw else None


def write_json(store, container: str, path: str, payload: dict, cache_seconds: int | None = None) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    cache = f"public, max-age={cache_seconds}" if cache_seconds is not None else None
    return store.write(container, path, data, "application/json; charset=utf-8", cache)
