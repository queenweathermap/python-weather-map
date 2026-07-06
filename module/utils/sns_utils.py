# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/sns_utils.py
#
# SNS 自動投稿ユーティリティ
#   ・Bluesky（AT Protocol / 無料）: 画像付き投稿
#
# 使い方:
#   from module.utils.sns_utils import post_bluesky
#   post_bluesky(text="...", png=png_bytes, alt="代替テキスト")
#
# 必要な環境変数（GitHub Actions secrets 推奨）:
#   BLUESKY_ENABLE=1
#   BLUESKY_HANDLE=xxxxx.bsky.social   （またはカスタムドメイン）
#   BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx  （アプリパスワード。通常のログインPW不可）
#
# アプリパスワードは Bluesky の Settings → App Passwords で発行する。
# =============================================================================

from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import requests

BSKY_PDS = os.environ.get("BLUESKY_PDS", "https://bsky.social").rstrip("/")
BSKY_BLOB_LIMIT = 950_000  # Bluesky の blob 上限(約1MB)より少し小さめに収める


def bluesky_enabled() -> bool:
    return (
        os.environ.get("BLUESKY_ENABLE", "0").lower() in ("1", "true", "yes", "on")
        and bool(os.environ.get("BLUESKY_HANDLE", "").strip())
        and bool(os.environ.get("BLUESKY_APP_PASSWORD", "").strip())
    )


def _fit_blob(png: bytes) -> tuple[bytes, str]:
    """
    Bluesky の blob 上限に収める。
    上限内の PNG はそのまま、超える場合は JPEG 化→必要なら段階的に品質/画素を落とす。
    """
    if len(png) <= BSKY_BLOB_LIMIT:
        return png, "image/png"

    try:
        from PIL import Image
    except Exception:
        # PIL が無い場合はそのまま返す（失敗しても投稿側で握りつぶす）
        return png, "image/png"

    im = Image.open(io.BytesIO(png)).convert("RGB")
    for q in (90, 85, 80, 72, 65):
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        if buf.tell() <= BSKY_BLOB_LIMIT:
            return buf.getvalue(), "image/jpeg"

    # まだ大きければ画素を落とす
    while im.width > 1000:
        im = im.resize((int(im.width * 0.85), int(im.height * 0.85)))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=72, optimize=True)
        if buf.tell() <= BSKY_BLOB_LIMIT:
            return buf.getvalue(), "image/jpeg"

    return buf.getvalue(), "image/jpeg"


def post_bluesky(*, text: str, png: bytes, alt: str = "") -> bool:
    """Bluesky に画像1枚付きで投稿する。成功で True。"""
    if not bluesky_enabled():
        print("[INFO] Bluesky 無効（BLUESKY_ENABLE / HANDLE / APP_PASSWORD 未設定）")
        return False

    handle = os.environ["BLUESKY_HANDLE"].strip()
    app_pw = os.environ["BLUESKY_APP_PASSWORD"].strip()

    try:
        # 1. セッション作成
        s = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_pw},
            timeout=60,
        )
        s.raise_for_status()
        sess = s.json()
        jwt = sess["accessJwt"]
        did = sess["did"]
        auth = {"Authorization": f"Bearer {jwt}"}

        # 2. 画像アップロード（blob）
        blob_bytes, mime = _fit_blob(png)
        up = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.repo.uploadBlob",
            headers={**auth, "Content-Type": mime},
            data=blob_bytes,
            timeout=120,
        )
        up.raise_for_status()
        blob = up.json()["blob"]

        # 3. 投稿レコード作成
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "langs": ["ja"],
            "embed": {
                "$type": "app.bsky.embed.images",
                "images": [{"alt": alt or text[:280], "image": blob}],
            },
        }
        cr = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.repo.createRecord",
            headers=auth,
            json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            timeout=60,
        )
        cr.raise_for_status()
        print("[OK] Bluesky posted")
        return True

    except Exception as e:
        print(f"[ERR] Bluesky post failed: {e}")
        return False
