# -*- coding: utf-8 -*-
"""
scripts/r2_utils.py

Cloudflare R2 (S3互換) にファイルをアップロードし、
外部参照用のURLを返すユーティリティ。

前提:
- R2バケットが作成済み
- 公開URL運用をするなら、バケットの Public access を有効化するか、
  もしくは R2 + カスタムドメイン(推奨) を設定する。

環境変数:
- R2_ACCOUNT_ID
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- R2_BUCKET
- R2_PUBLIC_BASE_URL (任意)
    例: https://r2.example.com/weather (末尾スラなし推奨)
    これを設定すると、アップロード後のURL生成にこのベースURLを使う
"""

from __future__ import annotations

import os
import mimetypes
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.client import Config


@dataclass
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: Optional[str] = None

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def load_r2_config() -> R2Config:
    account_id = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access_key_id = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_access_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    public_base_url = os.environ.get("R2_PUBLIC_BASE_URL", "").strip() or None

    missing = []
    if not account_id:
        missing.append("R2_ACCOUNT_ID")
    if not access_key_id:
        missing.append("R2_ACCESS_KEY_ID")
    if not secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY")
    if not bucket:
        missing.append("R2_BUCKET")

    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    # 末尾スラがあると urljoin 的に事故りやすいので除去
    if public_base_url:
        public_base_url = public_base_url.rstrip("/")

    return R2Config(
        account_id=account_id,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        bucket=bucket,
        public_base_url=public_base_url,
    )


def _make_s3_client(cfg: R2Config):
    # R2 は S3互換。Signature v4 を使う。
    session = boto3.session.Session()
    s3 = session.client(
        service_name="s3",
        endpoint_url=cfg.endpoint_url,
        aws_access_key_id=cfg.access_key_id,
        aws_secret_access_key=cfg.secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return s3


def guess_content_type(path: str) -> str:
    ctype, _ = mimetypes.guess_type(path)
    return ctype or "application/octet-stream"


def upload_file_to_r2(
    local_path: str,
    object_key: str,
    *,
    content_type: Optional[str] = None,
    cache_control: str = "public, max-age=31536000, immutable",
) -> str:
    """
    local_path を R2 にアップロードし、外部参照用のURLを返す。

    - object_key: バケット内のパス（例: "jma_adv/20260202/GSM/item01/ft03.png"）
    """
    cfg = load_r2_config()
    s3 = _make_s3_client(cfg)

    if content_type is None:
        content_type = guess_content_type(local_path)

    extra_args = {
        "ContentType": content_type,
        "CacheControl": cache_control,
    }

    s3.upload_file(
        Filename=local_path,
        Bucket=cfg.bucket,
        Key=object_key,
        ExtraArgs=extra_args,
    )

    return build_public_url(object_key)


def build_public_url(object_key: str) -> str:
    """
    公開参照URLを生成する。
    - R2_PUBLIC_BASE_URL があればそれを使う（推奨：カスタムドメイン）
    - なければ R2 のエンドポイントURL を返す（バケット公開設定に依存）
    """
    cfg = load_r2_config()
    object_key = object_key.lstrip("/")

    if cfg.public_base_url:
        # 例: https://r2.example.com/weather + /{object_key}
        return f"{cfg.public_base_url}/{object_key}"

    # R2デフォルトURL（公開設定してないと見れない）
    return f"{cfg.endpoint_url}/{cfg.bucket}/{object_key}"
