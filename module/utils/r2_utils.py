# -*- coding: utf-8 -*-
# =============================================================================
# scripts/r2_utils.py
#
# Cloudflare R2 (S3互換API) ユーティリティ
# - put_bytes(): bytesをR2へアップロード
# - make_url(): 公開URL（ASSET_BASE_URL）からオブジェクトURL生成
#
# 必要な環境変数（GitHub Actions secrets推奨）
#   R2_ACCOUNT_ID
#   R2_ACCESS_KEY_ID
#   R2_SECRET_ACCESS_KEY
#   R2_BUCKET
#   ASSET_BASE_URL          # 例: https://<your-bucket>.<your-account-or-managed>.r2.dev
#
# 任意
#   R2_PREFIX               # 例: "adv-tgv" （キーの先頭に付ける）
# =============================================================================

from __future__ import annotations

import os
from typing import Optional, Dict, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _must_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def _r2_endpoint() -> str:
    """
    Cloudflare R2 S3互換エンドポイント
    例: https://<account_id>.r2.cloudflarestorage.com
    """
    account_id = _must_env("R2_ACCOUNT_ID")
    return f"https://{account_id}.r2.cloudflarestorage.com"


def _client():
    """
    boto3 S3 client for R2
    - region_name は "auto" でOK（R2向け）
    - signature_version は v4
    """
    return boto3.client(
        "s3",
        endpoint_url=_r2_endpoint(),
        aws_access_key_id=_must_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_must_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def normalize_key(key: str) -> str:
    """
    R2のobject key正規化
    - 先頭の / を除去
    - R2_PREFIX があれば先頭に付ける
    """
    key = key.lstrip("/")
    prefix = _env("R2_PREFIX", "")
    if prefix:
        prefix = prefix.strip("/")

    return f"{prefix}/{key}" if prefix else key


def put_bytes(
    key: str,
    data: bytes,
    *,
    content_type: str = "application/octet-stream",
    cache_control: str = "public, max-age=300, must-revalidate",
    metadata: Optional[Dict[str, str]] = None,
) -> None:
    """
    bytes をR2へアップロードする。
    - 公開バケット（r2.dev等）にしていれば、ASSET_BASE_URL + key で閲覧できる。

    cache_control: 以前は "immutable, max-age=31536000"(1年キャッシュ)だったが、
    キー生成が発表時刻(9時/21時など固定枠)ベースのジョブでは、同じ枠内で
    複数回実行される(1日に複数回のスケジュール実行や手動再実行)と同じキーに
    上書きされることがあり、"immutable"のせいでCDN/ブラウザが最初にキャッシュ
    した古い内容をいつまでも返し続けてしまっていた(例: キャプション追加前の
    画像が半永久的に配信され続ける不具合の原因になった)。5分キャッシュ+
    must-revalidateにして、上書きが確実に反映されるようにする。
    """
    bucket = _must_env("R2_BUCKET")
    k = normalize_key(key)

    extra: Dict[str, Any] = {
        "ContentType": content_type,
        "CacheControl": cache_control,
    }
    if metadata:
        extra["Metadata"] = metadata

    s3 = _client()
    s3.put_object(Bucket=bucket, Key=k, Body=data, **extra)


def get_bytes(key: str) -> Optional[bytes]:
    """
    R2からbytesを取得する。オブジェクトが存在しなければNoneを返す
    （例: 状態ファイルの初回実行時にまだ何も無い場合）。
    """
    bucket = _must_env("R2_BUCKET")
    k = normalize_key(key)
    s3 = _client()
    try:
        resp = s3.get_object(Bucket=bucket, Key=k)
        return resp["Body"].read()
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            return None
        raise


def make_url(key: str) -> str:
    """
    公開URLを組み立てる（Notionに貼る用）
    - ASSET_BASE_URL は末尾スラッシュ無しを推奨
    """
    base = _must_env("ASSET_BASE_URL").rstrip("/")
    k = normalize_key(key)
    return f"{base}/{k}"
