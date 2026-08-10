# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/wordpress_utils.py
#
# WordPress (wx-chart.com) REST API 投稿ユーティリティ
#   ・認証: アプリケーションパスワード（Basic認証）
#   ・画像を /media にアップロード → 本文に埋め込んで /posts を publish（アイキャッチは設定しない）
#   ・タグは名前指定で自動解決（既存タグを検索、無ければ作成）して付与する
#
# 必要な環境変数（GitHub Actions secrets 推奨）:
#   WP_ENABLE        : "1" で有効化（既定 "1"。未設定/認証情報なしなら自動的に無効）
#   WP_USERNAME       : WordPressユーザー名
#   WP_APP_PASSWORD   : アプリケーションパスワード（半角スペース入り可）
#   WP_API_BASE       : 既定 "https://wx-chart.com/wp-json/wp/v2"
#
# 呼び出し側の方針:
#   WordPress側のAPIエラーはここで吸収し、失敗時は "" を返すだけにする
#   （呼び出し元のDiscord/SNS配信を止めないため）。
# =============================================================================

from __future__ import annotations

import os
from typing import List, Tuple

import requests

WP_API_BASE = os.environ.get("WP_API_BASE", "https://wx-chart.com/wp-json/wp/v2").rstrip("/")


def wp_enabled() -> bool:
    return (
        os.environ.get("WP_ENABLE", "1").lower() in ("1", "true", "yes", "on")
        and bool(os.environ.get("WP_USERNAME", "").strip())
        and bool(os.environ.get("WP_APP_PASSWORD", "").strip())
    )


def _auth() -> Tuple[str, str]:
    return (os.environ["WP_USERNAME"].strip(), os.environ["WP_APP_PASSWORD"].strip())


def upload_media(png: bytes, filename: str, alt_text: str = "") -> dict:
    """
    /media に画像をアップロードし、{"id":..., "source_url":...} を返す。
    失敗時は例外を投げる（呼び出し元でtry/exceptすること）。
    """
    r = requests.post(
        f"{WP_API_BASE}/media",
        auth=_auth(),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/png",
        },
        data=png,
        timeout=120,
    )
    r.raise_for_status()
    media = r.json()

    if alt_text:
        try:
            requests.post(
                f"{WP_API_BASE}/media/{media['id']}",
                auth=_auth(),
                json={"alt_text": alt_text},
                timeout=60,
            ).raise_for_status()
        except Exception as e:
            print(f"[WARN] WordPress alt_text設定失敗: {e}")

    return media


def get_or_create_tag(name: str) -> int:
    """
    /tags からタグ名で既存タームを検索し、無ければ作成してIDを返す。
    失敗時は例外を投げる。
    """
    r = requests.get(
        f"{WP_API_BASE}/tags",
        auth=_auth(),
        params={"search": name, "per_page": 100},
        timeout=30,
    )
    r.raise_for_status()
    for term in r.json():
        if term.get("name") == name:
            return term["id"]

    r = requests.post(
        f"{WP_API_BASE}/tags",
        auth=_auth(),
        json={"name": name},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def create_post(title: str, content_html: str, *, tag_ids: List[int] = (), status: str = "publish") -> dict:
    """
    /posts に記事を作成する。失敗時は例外を投げる。
    """
    r = requests.post(
        f"{WP_API_BASE}/posts",
        auth=_auth(),
        json={
            "title": title,
            "content": content_html,
            "status": status,
            "tags": list(tag_ids),
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def post_climate_article(
    title: str,
    images: List[Tuple[bytes, str]],
    description: str,
    *,
    tags: List[str] = (),
) -> str:
    """
    気象まとめ記事をWordPressに投稿する高レベル関数。

    images: [(png_bytes, filename), ...]  本文にこの順で並ぶ画像として埋め込む（アイキャッチは設定しない）。
    description: 本文の <p> とすべての画像の alt に使う説明文。
    tags: 記事に付けるタグ名のリスト（既存タグを検索し、無ければ自動作成）。

    成功時は投稿URL、失敗時（無効化含む）は "" を返す。
    ここで例外は握りつぶし、呼び出し元のDiscord/SNS配信を止めない。
    """
    if not wp_enabled():
        print("[INFO] WordPress 無効（WP_ENABLE / WP_USERNAME / WP_APP_PASSWORD 未設定）")
        return ""
    if not images:
        return ""

    try:
        uploaded = [upload_media(png, filename, description) for png, filename in images]

        body_parts = [
            f'<img src="{m["source_url"]}" alt="{description}" />' for m in uploaded
        ]
        body_parts.append(f"<p>{description}</p>")
        content_html = "\n".join(body_parts)

        tag_ids = []
        for name in tags:
            try:
                tag_ids.append(get_or_create_tag(name))
            except Exception as e:
                print(f"[WARN] WordPressタグ解決失敗（{name}）: {e}")

        post = create_post(title, content_html, tag_ids=tag_ids, status="publish")
        url = post.get("link", "")
        print(f"[OK] WordPress posted: {url}")
        return url
    except Exception as e:
        print(f"[ERR] WordPress post failed: {e}")
        return ""
