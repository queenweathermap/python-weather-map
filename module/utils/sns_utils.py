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
import time
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


# =============================================================================
# X (旧Twitter)  ※2026年2月以降は従量課金。tweepy で v1.1メディアアップ→v2投稿。
#   必要な環境変数:
#     X_ENABLE=1
#     X_API_KEY / X_API_SECRET            （consumer key/secret）
#     X_ACCESS_TOKEN / X_ACCESS_SECRET    （access token/secret）
# =============================================================================
def x_enabled() -> bool:
    return (
        os.environ.get("X_ENABLE", "0").lower() in ("1", "true", "yes", "on")
        and all(os.environ.get(k, "").strip() for k in
                ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))
    )


def post_x(*, text: str, png: bytes, alt: str = "") -> bool:
    """X に画像1枚付きで投稿する。成功で True。"""
    if not x_enabled():
        print("[INFO] X 無効（X_ENABLE / キー未設定）")
        return False
    try:
        import tweepy
    except Exception as e:
        print(f"[ERR] tweepy 未インストール: {e}")
        return False

    api_key = os.environ["X_API_KEY"].strip()
    api_secret = os.environ["X_API_SECRET"].strip()
    access_token = os.environ["X_ACCESS_TOKEN"].strip()
    access_secret = os.environ["X_ACCESS_SECRET"].strip()

    try:
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
        api = tweepy.API(auth)  # v1.1: メディアアップロード用
        media = api.media_upload(filename="post.png", file=io.BytesIO(png))
        if alt:
            try:
                api.create_media_metadata(media.media_id, alt)
            except Exception as e:
                print(f"[WARN] X alt設定失敗: {e}")

        client = tweepy.Client(
            consumer_key=api_key, consumer_secret=api_secret,
            access_token=access_token, access_token_secret=access_secret,
        )  # v2: 投稿作成用
        client.create_tweet(text=text[:280], media_ids=[media.media_id])
        print("[OK] X posted")
        return True
    except Exception as e:
        print(f"[ERR] X post failed: {e}")
        return False


# =============================================================================
# Threads (Meta)  ※無料。画像は「公開URL」からMetaが取得する。
#   必要な環境変数:
#     THREADS_ENABLE=1
#     THREADS_USER_ID
#     THREADS_ACCESS_TOKEN   （長期トークン）
#   仕様: 画像は幅320〜1440px / 8MB以下 / JPEG or PNG。作成→30秒以上待つ→publish。
# =============================================================================
def threads_enabled() -> bool:
    return (
        os.environ.get("THREADS_ENABLE", "0").lower() in ("1", "true", "yes", "on")
        and bool(os.environ.get("THREADS_USER_ID", "").strip())
        and bool(os.environ.get("THREADS_ACCESS_TOKEN", "").strip())
    )


def _threads_fit_png(png: bytes) -> bytes:
    """Threadsの幅上限(1440px)に収める。"""
    try:
        from PIL import Image
    except Exception:
        return png
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > 1440:
        h = max(1, int(im.height * 1440 / im.width))
        im = im.resize((1440, h))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def post_threads(*, text: str, png: bytes, r2_upload) -> bool:
    """
    Threads に画像1枚付きで投稿する。成功で True。
    画像は公開URLが必須のため、r2_upload(key, bytes)->url で一旦R2に上げてURLを渡す。
    """
    if not threads_enabled():
        print("[INFO] Threads 無効（THREADS_ENABLE / USER_ID / TOKEN 未設定）")
        return False
    if r2_upload is None:
        print("[ERR] Threads: 公開URLが必要（r2_upload 未指定）")
        return False

    uid = os.environ["THREADS_USER_ID"].strip()
    token = os.environ["THREADS_ACCESS_TOKEN"].strip()

    img = _threads_fit_png(png)
    key = f"threads/{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.png"
    image_url = r2_upload(key, img)
    if not image_url:
        print("[ERR] Threads: R2アップロード失敗（公開URLを用意できず）")
        return False

    base = "https://graph.threads.net/v1.0"
    try:
        c = requests.post(
            f"{base}/{uid}/threads",
            params={"media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": token},
            timeout=60,
        )
        c.raise_for_status()
        creation_id = c.json()["id"]

        time.sleep(35)  # Metaの処理待ち（30秒以上）

        p = requests.post(
            f"{base}/{uid}/threads_publish",
            params={"creation_id": creation_id, "access_token": token},
            timeout=60,
        )
        p.raise_for_status()
        print("[OK] Threads posted")
        return True
    except Exception as e:
        print(f"[ERR] Threads post failed: {e}")
        return False
