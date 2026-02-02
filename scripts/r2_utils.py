# -*- coding: utf-8 -*-
# module/utils/r2_utils.py
"""
Cloudflare R2 (S3互換) アップロード支援
- put_bytes: bytes をR2へアップロード
- make_url: Notion等で参照するURLを作る（public or presigned）
"""

import os
from typing import Optional

import boto3
from botocore.client import Config


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _must(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v


def r2_client():
    account_id = _must("R2_ACCOUNT_ID")
    access_key = _must("R2_ACCESS_KEY_ID")
    secret_key = _must("R2_SECRET_ACCESS_KEY")

    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def put_bytes(
    key: str,
    blob: bytes,
    *,
    content_type: str = "application/octet-stream",
    cache_control: str = "public, max-age=31536000, immutable",
) -> None:
    """
    bytesをR2へアップロード
    """
    bucket = _must("R2_BUCKET")
    s3 = r2_client()

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=blob,
        ContentType=content_type,
        CacheControl=cache_control,
    )


def make_url(key: str) -> str:
    """
    Notionに貼るURLを作る
    - R2_URL_MODE=public: R2_PUBLIC_BASE_URL + /key
    - R2_URL_MODE=presigned: presigned URL（期限付き）
    """
    mode = _env("R2_URL_MODE", "public").lower()

    if mode == "public":
        base = _must("R2_PUBLIC_BASE_URL").rstrip("/")
        return f"{base}/{key}"

    # presigned
    bucket = _must("R2_BUCKET")
    s3 = r2_client()
    exp = int(_env("R2_PRESIGN_EXPIRE_SEC", "604800"))  # default 7 days

    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=exp,
    )
