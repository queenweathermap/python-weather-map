# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/notion_utils.py
#
# Notion API ユーティリティ
# - DBへ1行（=ページ）を作る: create_db_row()
# - ページ配下にブロック追加:
#     append_heading(), append_toggle(), append_images(),
#     append_text(), append_code_block(), append_files(), append_bookmark()
# - 代表画像をカバーにする: set_page_cover()
#
# 必要な環境変数
#   NOTION_TOKEN
#
# DB運用（本命）
#   NOTION_DATABASE_ID
#
# 任意（機能ON/OFF）
#   NOTION_ENABLE=1         # 0なら何もしない（テスト用）
#
# 任意（DBプロパティ名が環境で違う場合の上書き）
#   NOTION_PROP_TITLE="名前"
#   NOTION_PROP_CATEGORY="区分"
#   NOTION_PROP_INIT_JST="初期時刻（JST）"
#   NOTION_PROP_MEMO="メモ"
#   NOTION_PROP_R2URL="R2 URL"
#   NOTION_PROP_AUTOGEN="自動生成"
#   NOTION_PROP_RJTD="RJTD"
#   NOTION_PROP_PREFIX="prefix"
# =============================================================================

from __future__ import annotations

import os
import time
from typing import List, Optional, Dict, Any, Tuple

import requests


NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _must_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def notion_enabled() -> bool:
    v = _env("NOTION_ENABLE", "1").lower()
    return v in ("1", "true", "yes", "on")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_must_env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# -----------------------------------------------------------------------------
# DB property names (overrideable)
# -----------------------------------------------------------------------------
def _prop_title() -> str:
    return _env("NOTION_PROP_TITLE", "名前")


def _prop_category() -> str:
    return _env("NOTION_PROP_CATEGORY", "区分")


def _prop_init_jst() -> str:
    return _env("NOTION_PROP_INIT_JST", "初期時刻（JST）")


def _prop_memo() -> str:
    return _env("NOTION_PROP_MEMO", "メモ")


def _prop_r2url() -> str:
    return _env("NOTION_PROP_R2URL", "R2 URL")


def _prop_autogen() -> str:
    return _env("NOTION_PROP_AUTOGEN", "自動生成")


def _prop_rjtd() -> str:
    return _env("NOTION_PROP_RJTD", "RJTD")


def _prop_prefix() -> str:
    return _env("NOTION_PROP_PREFIX", "prefix")


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------
def _safe_preview_text(s: str, limit: int = 180) -> str:
    s = (s or "").replace("\n", " ")
    return s[:limit] + ("..." if len(s) > limit else "")


def _post_children_once(page_or_block_id: str, children: List[dict], *, timeout: int = 60) -> requests.Response:
    payload = {"children": children}
    return requests.patch(
        f"{API_BASE}/blocks/{page_or_block_id}/children",
        headers=_headers(),
        json=payload,
        timeout=timeout,
    )


def _append_children_with_retry(
    page_or_block_id: str,
    children: List[dict],
    *,
    label: str = "children",
    max_retries: int = 3,
    sleep_seconds: float = 1.2,
) -> None:
    """
    Notion blocks/{id}/children 追加の堅牢版
    - 429 / 5xx はリトライ
    - 400 などで children が複数なら半分に分割して再試行
    - 1件でも失敗する場合は詳細ログを出して raise
    """
    if not children:
        return

    attempt = 0
    last_exc: Optional[Exception] = None

    while attempt < max_retries:
        attempt += 1
        try:
            r = _post_children_once(page_or_block_id, children)
            r.raise_for_status()
            if attempt > 1:
                print(f"[NOTION][OK] {label}: recovered on retry {attempt}/{max_retries} size={len(children)}")
            return
        except requests.HTTPError as e:
            last_exc = e
            resp = e.response
            status = resp.status_code if resp is not None else None
            body = ""
            try:
                body = _safe_preview_text(resp.text if resp is not None else "")
            except Exception:
                body = ""

            print(
                f"[NOTION][WARN] append failed "
                f"label={label} block={page_or_block_id} size={len(children)} "
                f"attempt={attempt}/{max_retries} status={status} body={body}"
            )

            # 429 / 5xx は待ってリトライ
            if status == 429:
                retry_after = 0
                try:
                    retry_after = int(resp.headers.get("Retry-After", "0"))
                except Exception:
                    retry_after = 0
                wait = retry_after if retry_after > 0 else sleep_seconds * attempt
                time.sleep(wait)
                continue

            if status is not None and 500 <= status <= 599:
                time.sleep(sleep_seconds * attempt)
                continue

            # 400系などで複数件なら分割して再帰的に投入
            if len(children) > 1:
                mid = max(1, len(children) // 2)
                left = children[:mid]
                right = children[mid:]
                print(
                    f"[NOTION][INFO] split retry "
                    f"label={label} block={page_or_block_id} "
                    f"{len(children)} -> {len(left)} + {len(right)}"
                )
                _append_children_with_retry(
                    page_or_block_id,
                    left,
                    label=f"{label}/L",
                    max_retries=max_retries,
                    sleep_seconds=sleep_seconds,
                )
                _append_children_with_retry(
                    page_or_block_id,
                    right,
                    label=f"{label}/R",
                    max_retries=max_retries,
                    sleep_seconds=sleep_seconds,
                )
                return

            # 1件で落ちたときは内容を少し出す
            bad = children[0]
            print(f"[NOTION][ERROR] single child rejected label={label} child={bad}")
            raise

        except requests.RequestException as e:
            last_exc = e
            print(
                f"[NOTION][WARN] network/request error "
                f"label={label} block={page_or_block_id} size={len(children)} "
                f"attempt={attempt}/{max_retries} error={e}"
            )
            time.sleep(sleep_seconds * attempt)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Notion append failed: {label}")


# -----------------------------------------------------------------------------
# DB row create
# -----------------------------------------------------------------------------
def create_db_row(
    *,
    title: str,
    category: str,
    init_jst_iso: str,
    memo: str = "",
    rjtd: str = "",
    prefix: str = "",
    r2_url: str = "",
    autogen: bool = True,
    icon_emoji: str = "🗺️",
) -> Optional[str]:
    if not notion_enabled():
        return None

    db_id = _must_env("NOTION_DATABASE_ID")

    props: Dict[str, Any] = {
        _prop_title(): {"title": [{"type": "text", "text": {"content": title}}]},
        _prop_category(): {"select": {"name": category}},
        _prop_init_jst(): {"date": {"start": init_jst_iso}},
    }

    if memo:
        props[_prop_memo()] = {"rich_text": [{"type": "text", "text": {"content": memo}}]}

    if rjtd:
        props[_prop_rjtd()] = {"rich_text": [{"type": "text", "text": {"content": rjtd}}]}
    if prefix:
        props[_prop_prefix()] = {"rich_text": [{"type": "text", "text": {"content": prefix}}]}

    if r2_url:
        props[_prop_r2url()] = {"url": r2_url}
    if autogen is not None:
        props[_prop_autogen()] = {"checkbox": bool(autogen)}

    payload = {
        "parent": {"type": "database_id", "database_id": db_id},
        "icon": {"type": "emoji", "emoji": icon_emoji},
        "properties": props,
    }

    r = requests.post(f"{API_BASE}/pages", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def set_page_cover(page_id: str, image_url: str) -> None:
    if not notion_enabled():
        return
    if not image_url:
        return

    payload = {"cover": {"type": "external", "external": {"url": image_url}}}
    r = requests.patch(f"{API_BASE}/pages/{page_id}", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()


# -----------------------------------------------------------------------------
# Notion File Upload API
# -----------------------------------------------------------------------------
def create_file_upload_from_url(
    url: str,
    *,
    filename: str = "",
    content_type: str = "image/png",
) -> str:
    """
    外部URL上のファイルをNotion管理ストレージへ取り込むための
    File Uploadオブジェクトを作成する。
    R2を一時置き場にしてNotionへ移行する運用で使う。
    """
    if not notion_enabled():
        return ""

    url = (url or "").strip()
    if not url:
        return ""

    payload: Dict[str, Any] = {
        "mode": "external_url",
        "external_url": url,
    }
    if filename:
        payload["filename"] = filename
    if content_type:
        payload["content_type"] = content_type

    r = requests.post(f"{API_BASE}/file_uploads", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def retrieve_file_upload(file_upload_id: str) -> Dict[str, Any]:
    if not notion_enabled():
        return {}

    r = requests.get(f"{API_BASE}/file_uploads/{file_upload_id}", headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def wait_file_upload_uploaded(
    file_upload_id: str,
    *,
    timeout_seconds: int = 180,
    poll_seconds: float = 2.0,
) -> Dict[str, Any]:
    """
    external_url import は非同期なので uploaded / failed まで待つ。
    """
    deadline = time.time() + timeout_seconds
    last: Dict[str, Any] = {}

    while time.time() < deadline:
        last = retrieve_file_upload(file_upload_id)
        status = (last.get("status") or "").lower()

        if status == "uploaded":
            return last
        if status in ("failed", "expired"):
            raise RuntimeError(f"Notion file_upload {file_upload_id} status={status}: {last}")

        time.sleep(poll_seconds)

    raise TimeoutError(f"Notion file_upload timeout: id={file_upload_id} last={last}")


def append_uploaded_images(
    page_or_block_id: str,
    upload_ids: List[str],
    *,
    captions: Optional[List[str]] = None,
    chunk: int = 10,
) -> None:
    """
    Notion管理ストレージに取り込み済みの file_upload を画像ブロックとして追加する。
    """
    if not notion_enabled():
        return

    upload_ids = [u for u in (upload_ids or []) if u]
    if not upload_ids:
        return

    captions = captions or []

    for i in range(0, len(upload_ids), chunk):
        part = upload_ids[i:i + chunk]
        children: List[dict] = []

        for j, upload_id in enumerate(part):
            cap = captions[i + j] if i + j < len(captions) else ""
            block: Dict[str, Any] = {
                "object": "block",
                "type": "image",
                "image": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                },
            }
            if cap:
                block["image"]["caption"] = [{"type": "text", "text": {"content": cap}}]
            children.append(block)

        _append_children_with_retry(
            page_or_block_id,
            children,
            label=f"uploaded_images[{i}:{i + len(part)}]",
        )


def append_imported_images_from_urls(
    page_or_block_id: str,
    items: List[Tuple[str, str, str]],
    *,
    chunk: int = 10,
    timeout_seconds: int = 180,
    poll_seconds: float = 2.0,
) -> None:
    """
    R2などの外部URL画像をNotion管理ストレージに取り込んでから、
    file_upload画像ブロックとしてページに追加する。

    items: [(filename, url, content_type), ...]
    """
    if not notion_enabled():
        return

    upload_ids: List[str] = []
    captions: List[str] = []

    for filename, url, content_type in items:
        url = (url or "").strip()
        if not url:
            continue

        print(f"[NOTION] import image from URL: {filename} {url}")
        upload_id = create_file_upload_from_url(
            url,
            filename=filename,
            content_type=content_type or "image/png",
        )
        wait_file_upload_uploaded(
            upload_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        upload_ids.append(upload_id)
        captions.append(filename)

    append_uploaded_images(page_or_block_id, upload_ids, captions=captions, chunk=chunk)


# -----------------------------------------------------------------------------
# Blocks append
# -----------------------------------------------------------------------------
def append_heading(page_or_block_id: str, text: str, *, level: int = 2) -> Optional[str]:
    if not notion_enabled():
        return None

    if level not in (2, 3):
        level = 2
    t = "heading_2" if level == 2 else "heading_3"

    payload = {
        "children": [
            {
                "object": "block",
                "type": t,
                t: {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }
        ]
    }

    r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()

    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    return results[0]["id"]


def append_toggle(page_or_block_id: str, title: str) -> Optional[str]:
    if not notion_enabled():
        return None
    if not title:
        return None

    payload = {
        "children": [
            {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [{"type": "text", "text": {"content": title}}],
                    "children": [],
                },
            }
        ]
    }
    r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
    r.raise_for_status()

    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    return results[0]["id"]


def append_images(page_or_block_id: str, urls: List[str], *, chunk: int = 10) -> None:
    """
    外部URL画像を Notion に埋め込みで追加（ページでもトグルでもOK）
    - chunk を小さめに
    - 失敗時は自動分割・リトライ
    """
    if not notion_enabled():
        return

    urls = [u for u in (urls or []) if u]
    if not urls:
        return

    for i in range(0, len(urls), chunk):
        part = urls[i:i + chunk]
        children = [
            {
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": u}},
            }
            for u in part
        ]

        _append_children_with_retry(
            page_or_block_id,
            children,
            label=f"images[{i}:{i + len(part)}]",
        )


def append_text(page_or_block_id: str, text: str, *, chunk_chars: int = 1800) -> None:
    if not notion_enabled():
        return

    text = (text or "").strip()
    if not text:
        return

    for i in range(0, len(text), chunk_chars):
        part = text[i:i + chunk_chars]
        payload = {
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": part}}]},
                }
            ]
        }
        r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()


def append_code_block(page_or_block_id: str, text: str, *, language: str = "plain text", chunk_chars: int = 1800) -> None:
    if not notion_enabled():
        return

    text = (text or "").rstrip()
    if not text:
        return

    for i in range(0, len(text), chunk_chars):
        part = text[i:i + chunk_chars]
        payload = {
            "children": [
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": part}}],
                        "language": language,
                    },
                }
            ]
        }
        r = requests.patch(f"{API_BASE}/blocks/{page_or_block_id}/children", headers=_headers(), json=payload, timeout=60)
        r.raise_for_status()


def append_files(page_or_block_id: str, files: List[dict], *, chunk: int = 20) -> None:
    if not notion_enabled():
        return

    files = [f for f in (files or []) if f.get("url")]
    if not files:
        return

    for i in range(0, len(files), chunk):
        part = files[i:i + chunk]
        children = []
        for f in part:
            url = (f.get("url") or "").strip()
            name = (f.get("name") or "").strip()

            file_obj = {
                "object": "block",
                "type": "file",
                "file": {"type": "external", "external": {"url": url}},
            }
            if name:
                file_obj["file"]["caption"] = [{"type": "text", "text": {"content": name}}]

            children.append(file_obj)

        _append_children_with_retry(
            page_or_block_id,
            children,
            label=f"files[{i}:{i + len(part)}]",
        )


def append_bookmark(page_or_block_id: str, url: str, *, caption: str = "") -> None:
    if not notion_enabled():
        return

    url = (url or "").strip()
    if not url:
        return

    block: Dict[str, Any] = {
        "object": "block",
        "type": "bookmark",
        "bookmark": {"url": url},
    }

    if caption:
        block["bookmark"]["caption"] = [{"type": "text", "text": {"content": caption}}]

    _append_children_with_retry(
        page_or_block_id,
        [block],
        label="bookmark",
    )
