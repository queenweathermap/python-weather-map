# -*- coding: utf-8 -*-
"""
Delete old Cloudflare R2 objects by LastModified.

Required env:
  R2_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET

Optional env:
  R2_PREFIX=weathercaster
  R2_RETENTION_DAYS=30
  R2_CLEANUP_DRY_RUN=0
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module.utils.recent_items import cleanup_old_recent_items


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def main() -> None:
    account_id = env("R2_ACCOUNT_ID")
    access_key = env("R2_ACCESS_KEY_ID")
    secret_key = env("R2_SECRET_ACCESS_KEY")
    bucket = env("R2_BUCKET")
    prefix = env("R2_PREFIX", "weathercaster").strip("/")
    retention_days = int(env("R2_RETENTION_DAYS", "30"))
    dry_run = env("R2_CLEANUP_DRY_RUN", "0").lower() in ("1", "true", "yes", "on")

    if not all([account_id, access_key, secret_key, bucket]):
        raise RuntimeError("R2 env missing: R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET")

    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    list_prefix = f"{prefix}/" if prefix else ""

    print(f"[R2-CLEANUP] bucket={bucket} prefix={list_prefix!r} retention_days={retention_days} cutoff={cutoff.isoformat()} dry_run={dry_run}")

    paginator = s3.get_paginator("list_objects_v2")
    delete_batch = []
    checked = 0
    deleted = 0
    bytes_deleted = 0

    for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
        for obj in page.get("Contents", []):
            checked += 1
            key = obj["Key"]
            last_modified = obj["LastModified"]
            size = int(obj.get("Size") or 0)

            if last_modified >= cutoff:
                continue

            print(f"[R2-CLEANUP] old: {last_modified.isoformat()} {size} {key}")
            bytes_deleted += size
            deleted += 1
            delete_batch.append({"Key": key})

            if len(delete_batch) >= 1000:
                if not dry_run:
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": delete_batch})
                delete_batch = []

    if delete_batch and not dry_run:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": delete_batch})

    print(f"[R2-CLEANUP] checked={checked} deleted={deleted} bytes_deleted={bytes_deleted}")

    if not dry_run:
        # R2の画像が消えた後もPWA配信履歴（ギャラリー表示）にリンク切れの項目が
        # 残らないよう、同じ保存期間で古い記録を削除する。
        cleanup_old_recent_items(retention_days)


if __name__ == "__main__":
    main()
