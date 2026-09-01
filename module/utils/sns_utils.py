# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/sns_utils.py
#
# SNS 自動投稿ユーティリティ（複数画像対応 = 1投稿に複数枚）
#   ・Bluesky（AT Protocol / 無料）      : embed.images に最大4枚
#   ・Threads（Meta / 無料）             : 1枚=単一投稿 / 2枚以上=カルーセル
#   ・Facebook Page（Meta / 無料）       : 1枚=通常投稿 / 2枚以上=まとめてfeedに添付
#   ・Instagram（Meta / 無料）           : 1枚=単一投稿 / 2枚以上=カルーセル
#
# 画像は images=[(png_bytes, alt), ...] の形で渡す。
#
# X（旧Twitter）は有料枠を使わないため対応を廃止した。
#
# 必要な環境変数（GitHub Actions secrets 推奨）:
#   Bluesky   : BLUESKY_ENABLE / BLUESKY_HANDLE / BLUESKY_APP_PASSWORD
#   Threads   : THREADS_ENABLE / THREADS_USER_ID / THREADS_ACCESS_TOKEN
#   Facebook  : FACEBOOK_ENABLE / FACEBOOK_PAGE_ID / FACEBOOK_PAGE_ACCESS_TOKEN
#   Instagram : INSTAGRAM_ENABLE / INSTAGRAM_USER_ID / INSTAGRAM_ACCESS_TOKEN
# =============================================================================

from __future__ import annotations

import io
import json
import os
import time
from datetime import datetime, timezone
from typing import List, Tuple

import requests

Image_ = Tuple[bytes, str]  # (png_bytes, alt)


def _wait_container_ready(base: str, container_id: str, token: str, *,
                           timeout: float = 60.0, interval: float = 2.0) -> bool:
    """
    Threads/Instagramのメディアコンテナは作成が非同期。
    status が FINISHED になるまでポーリングしてから使う（カルーセル作成・publish前に必須）。
    未完了のままカルーセルの children に渡すと "Invalid Carousel Children" で弾かれるため。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{base}/{container_id}",
                params={"fields": "status,error_message", "access_token": token},
                timeout=30,
            )
            if r.ok:
                status = r.json().get("status")
                if status == "FINISHED":
                    return True
                if status == "ERROR":
                    print(f"[ERR] media container error: {r.json()}")
                    return False
        except Exception as e:
            print(f"[WARN] container status check failed: {e}")
        time.sleep(interval)
    print(f"[WARN] media container not ready in time: {container_id}")
    return False

BSKY_PDS = os.environ.get("BLUESKY_PDS", "https://bsky.social").rstrip("/")
BSKY_BLOB_LIMIT = 950_000  # Bluesky の blob 上限(約1MB)より少し小さめ


# =============================================================================
# Discord（1メッセージ・複数画像添付）
# =============================================================================
def post_discord_images(
    *, webhook_url: str, content: str,
    images: List[Tuple[str, bytes]], r2_links: List[Tuple[str, str]] = (),
) -> bool:
    """
    images   : [(filename, png_bytes), ...] を1メッセージに添付
    r2_links : [(ラベル, url), ...] を本文に太字リンクで付与
    """
    if not webhook_url:
        print("[INFO] Discord 無効（webhook 未設定）")
        return False

    body = content
    link_parts = [f"**[★{label}]({u})**" for label, u in r2_links if u]
    if link_parts:
        body += "\n" + " ／ ".join(link_parts)

    files = {}
    for i, (fname, png) in enumerate(images):
        files[f"files[{i}]"] = (fname, io.BytesIO(png), "image/png")

    payload = {"content": body[:1900], "allowed_mentions": {"parse": []}, "flags": 4}
    try:
        r = requests.post(
            webhook_url,
            data={"payload_json": json.dumps(payload, ensure_ascii=False)},
            files=files,
            timeout=180,
        )
        r.raise_for_status()
        print(f"[OK] Discord posted ({len(images)} images)")
        return True
    except Exception as e:
        print(f"[ERR] Discord post failed: {e}")
        return False


# =============================================================================
# Bluesky
# =============================================================================
def bluesky_enabled() -> bool:
    return (
        os.environ.get("BLUESKY_ENABLE", "0").lower() in ("1", "true", "yes", "on")
        and bool(os.environ.get("BLUESKY_HANDLE", "").strip())
        and bool(os.environ.get("BLUESKY_APP_PASSWORD", "").strip())
    )


def _fit_blob(png: bytes) -> Tuple[bytes, str]:
    """Bluesky の blob 上限に収める。超える場合は JPEG 化→品質/画素を落とす。"""
    if len(png) <= BSKY_BLOB_LIMIT:
        return png, "image/png"
    try:
        from PIL import Image
    except Exception:
        return png, "image/png"
    im = Image.open(io.BytesIO(png)).convert("RGB")
    for q in (90, 85, 80, 72, 65):
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        if buf.tell() <= BSKY_BLOB_LIMIT:
            return buf.getvalue(), "image/jpeg"
    while im.width > 1000:
        im = im.resize((int(im.width * 0.85), int(im.height * 0.85)))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=72, optimize=True)
        if buf.tell() <= BSKY_BLOB_LIMIT:
            return buf.getvalue(), "image/jpeg"
    return buf.getvalue(), "image/jpeg"


def post_bluesky(*, text: str, images: List[Image_]) -> bool:
    """Bluesky に画像付きで投稿（images=[(png, alt), ...] 最大4枚）。成功で True。"""
    if not bluesky_enabled():
        print("[INFO] Bluesky 無効（BLUESKY_ENABLE / HANDLE / APP_PASSWORD 未設定）")
        return False
    images = list(images)[:4]
    if not images:
        return False

    handle = os.environ["BLUESKY_HANDLE"].strip()
    app_pw = os.environ["BLUESKY_APP_PASSWORD"].strip()
    try:
        s = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_pw}, timeout=60,
        )
        s.raise_for_status()
        sess = s.json()
        auth = {"Authorization": f"Bearer {sess['accessJwt']}"}
        did = sess["did"]

        img_records = []
        for png, alt in images:
            blob_bytes, mime = _fit_blob(png)
            up = requests.post(
                f"{BSKY_PDS}/xrpc/com.atproto.repo.uploadBlob",
                headers={**auth, "Content-Type": mime}, data=blob_bytes, timeout=120,
            )
            up.raise_for_status()
            img_records.append({"alt": alt or text[:280], "image": up.json()["blob"]})

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "langs": ["ja"],
            "embed": {"$type": "app.bsky.embed.images", "images": img_records},
        }
        cr = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.repo.createRecord",
            headers=auth,
            json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            timeout=60,
        )
        cr.raise_for_status()
        print(f"[OK] Bluesky posted ({len(images)} images)")
        return True
    except Exception as e:
        print(f"[ERR] Bluesky post failed: {e}")
        return False


# =============================================================================
# Threads (Meta) ※無料。画像は公開URL(R2)からMetaが取得。2枚以上はカルーセル。
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


def post_threads(*, text: str, images: List[Image_], r2_upload) -> bool:
    """
    Threads に投稿。1枚=単一投稿 / 2枚以上=カルーセル。成功で True。
    画像は公開URLが必須のため、r2_upload(key, bytes)->url で一旦R2に上げてURLを渡す。
    """
    if not threads_enabled():
        print("[INFO] Threads 無効（THREADS_ENABLE / USER_ID / TOKEN 未設定）")
        return False
    if r2_upload is None:
        print("[ERR] Threads: 公開URLが必要（r2_upload 未指定）")
        return False

    images = list(images)
    if not images:
        return False

    uid = os.environ["THREADS_USER_ID"].strip()
    token = os.environ["THREADS_ACCESS_TOKEN"].strip()
    base = "https://graph.threads.net/v1.0"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    # 各画像をR2の公開URLへ
    urls: List[Tuple[str, str]] = []  # (image_url, alt)
    for i, (png, alt) in enumerate(images):
        u = r2_upload(f"threads/{ts}_{i}.png", _threads_fit_png(png))
        if not u:
            print("[ERR] Threads: R2アップロード失敗（公開URLを用意できず）")
            return False
        urls.append((u, alt))

    try:
        if len(urls) == 1:
            image_url, alt = urls[0]
            params = {"media_type": "IMAGE", "image_url": image_url, "text": text, "access_token": token}
            if alt:
                params["alt_text"] = alt
            c = requests.post(f"{base}/{uid}/threads", params=params, timeout=60)
            c.raise_for_status()
            creation_id = c.json()["id"]
        else:
            # カルーセル: 各画像をitemコンテナ化 → 準備完了を待つ → CAROUSEL親
            child_ids = []
            for image_url, alt in urls:
                params = {"media_type": "IMAGE", "image_url": image_url,
                          "is_carousel_item": "true", "access_token": token}
                if alt:
                    params["alt_text"] = alt
                cc = requests.post(f"{base}/{uid}/threads", params=params, timeout=60)
                cc.raise_for_status()
                child_ids.append(cc.json()["id"])
            for cid in child_ids:
                _wait_container_ready(base, cid, token)
            c = requests.post(
                f"{base}/{uid}/threads",
                params={"media_type": "CAROUSEL", "children": ",".join(child_ids),
                        "text": text, "access_token": token},
                timeout=60,
            )
            c.raise_for_status()
            creation_id = c.json()["id"]

        time.sleep(35)  # Metaの処理待ち（30秒以上）

        p = requests.post(
            f"{base}/{uid}/threads_publish",
            params={"creation_id": creation_id, "access_token": token}, timeout=60,
        )
        p.raise_for_status()
        print(f"[OK] Threads posted ({len(urls)} images{' carousel' if len(urls) > 1 else ''})")
        return True
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] Threads post failed: {e} {body}")
        return False


# =============================================================================
# Facebook Page ※無料。画像は直接バイナリでアップロードするため公開URL不要。
#   1枚=通常の写真投稿 / 2枚以上=未公開アップロード後にfeedへまとめて添付。
# =============================================================================
def facebook_enabled() -> bool:
    return (
        os.environ.get("FACEBOOK_ENABLE", "0").lower() in ("1", "true", "yes", "on")
        and bool(os.environ.get("FACEBOOK_PAGE_ID", "").strip())
        and bool(os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip())
    )


def post_facebook(*, text: str, images: List[Image_]) -> bool:
    """Facebookページに画像付きで投稿（images=[(png, alt), ...]）。成功で True。"""
    if not facebook_enabled():
        print("[INFO] Facebook 無効（FACEBOOK_ENABLE / PAGE_ID / PAGE_ACCESS_TOKEN 未設定）")
        return False
    images = list(images)
    if not images:
        return False

    page_id = os.environ["FACEBOOK_PAGE_ID"].strip()
    token = os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"].strip()
    base = "https://graph.facebook.com/v21.0"

    try:
        if len(images) == 1:
            png, _alt = images[0]
            r = requests.post(
                f"{base}/{page_id}/photos",
                data={"caption": text, "access_token": token},
                files={"source": ("image.png", io.BytesIO(png), "image/png")},
                timeout=120,
            )
            r.raise_for_status()
            print("[OK] Facebook posted (1 image)")
            return True

        media_ids = []
        for png, _alt in images:
            r = requests.post(
                f"{base}/{page_id}/photos",
                data={"published": "false", "access_token": token},
                files={"source": ("image.png", io.BytesIO(png), "image/png")},
                timeout=120,
            )
            r.raise_for_status()
            media_ids.append(r.json()["id"])

        attached_media = [{"media_fbid": mid} for mid in media_ids]
        r2 = requests.post(
            f"{base}/{page_id}/feed",
            data={"message": text, "attached_media": json.dumps(attached_media), "access_token": token},
            timeout=60,
        )
        r2.raise_for_status()
        print(f"[OK] Facebook posted ({len(images)} images)")
        return True
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] Facebook post failed: {e} {body}")
        return False


# =============================================================================
# Instagram (Meta) ※無料。Threadsと同じMeta Graph API基盤（graph.facebook.com）。
#   画像は公開URL(R2)からMetaが取得。2枚以上はカルーセル（最大10枚）。
# =============================================================================
def instagram_enabled() -> bool:
    return (
        os.environ.get("INSTAGRAM_ENABLE", "0").lower() in ("1", "true", "yes", "on")
        and bool(os.environ.get("INSTAGRAM_USER_ID", "").strip())
        and bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip())
    )


def _instagram_fit_image(png: bytes) -> bytes:
    """Instagramの幅上限(1440px)に収め、JPEG化する。"""
    try:
        from PIL import Image
    except Exception:
        return png
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > 1440:
        h = max(1, int(im.height * 1440 / im.width))
        im = im.resize((1440, h))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()


def post_instagram(*, text: str, images: List[Image_], r2_upload) -> bool:
    """
    Instagram に投稿。1枚=単一投稿 / 2枚以上=カルーセル。成功で True。
    画像は公開URLが必須のため、r2_upload(key, bytes)->url で一旦R2に上げてURLを渡す。
    """
    if not instagram_enabled():
        print("[INFO] Instagram 無効（INSTAGRAM_ENABLE / USER_ID / TOKEN 未設定）")
        return False
    if r2_upload is None:
        print("[ERR] Instagram: 公開URLが必要（r2_upload 未指定）")
        return False

    images = list(images)[:10]  # Instagramカルーセルは最大10枚
    if not images:
        return False

    uid = os.environ["INSTAGRAM_USER_ID"].strip()
    token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
    base = "https://graph.facebook.com/v21.0"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    # 各画像をR2の公開URLへ
    urls: List[Tuple[str, str]] = []  # (image_url, alt)
    for i, (png, alt) in enumerate(images):
        u = r2_upload(f"instagram/{ts}_{i}.jpg", _instagram_fit_image(png))
        if not u:
            print("[ERR] Instagram: R2アップロード失敗（公開URLを用意できず）")
            return False
        urls.append((u, alt))

    try:
        if len(urls) == 1:
            image_url, alt = urls[0]
            params = {"image_url": image_url, "caption": text, "access_token": token}
            if alt:
                params["alt_text"] = alt
            c = requests.post(f"{base}/{uid}/media", params=params, timeout=60)
            c.raise_for_status()
            creation_id = c.json()["id"]
        else:
            # カルーセル: 各画像をitemコンテナ化 → 準備完了を待つ → CAROUSEL親
            child_ids = []
            for image_url, alt in urls:
                params = {"image_url": image_url, "is_carousel_item": "true", "access_token": token}
                if alt:
                    params["alt_text"] = alt
                cc = requests.post(f"{base}/{uid}/media", params=params, timeout=60)
                cc.raise_for_status()
                child_ids.append(cc.json()["id"])
            for cid in child_ids:
                _wait_container_ready(base, cid, token)
            c = requests.post(
                f"{base}/{uid}/media",
                params={"media_type": "CAROUSEL", "children": ",".join(child_ids),
                        "caption": text, "access_token": token},
                timeout=60,
            )
            c.raise_for_status()
            creation_id = c.json()["id"]

        time.sleep(35)  # Metaの処理待ち（Threadsと同様30秒以上）

        p = requests.post(
            f"{base}/{uid}/media_publish",
            params={"creation_id": creation_id, "access_token": token}, timeout=60,
        )
        p.raise_for_status()
        print(f"[OK] Instagram posted ({len(urls)} images{' carousel' if len(urls) > 1 else ''})")
        return True
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] Instagram post failed: {e} {body}")
        return False
