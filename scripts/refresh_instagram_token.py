# -*- coding: utf-8 -*-
# =============================================================================
# scripts/refresh_instagram_token.py
#
# Instagram(Meta) 長期アクセストークンを自動延長し、GitHub Secrets を更新する。
#
#   1. 保存済みの長期ユーザートークンを graph.facebook.com/oauth/access_token で
#      再交換し、新しい60日ユーザートークンを取得
#   2. /me/accounts で177chartページの新しいページアクセストークンを取得
#      （投稿(post_instagram)にはこのページトークンを使う）
#   3. リポジトリの公開鍵で暗号化し、Secrets INSTAGRAM_USER_TOKEN /
#      INSTAGRAM_ACCESS_TOKEN を上書き
#
# 必要な環境変数:
#   INSTAGRAM_USER_TOKEN   現在の長期ユーザートークン（Secretから）
#   META_APP_ID            wxchart-poster の App ID
#   META_APP_SECRET        wxchart-poster の App Secret（Secretから）
#   GH_PAT                 細粒度PAT（このリポジトリの Secrets: Read and write 権限）
#   GITHUB_REPOSITORY      "owner/repo"（GitHub Actionsが自動で付与）
#
# 任意:
#   INSTAGRAM_PAGE_ID      177chartページのID（既定値あり）
# =============================================================================

from __future__ import annotations

import base64
import os
import sys

import requests
from nacl import encoding, public

DEFAULT_PAGE_ID = "1265931083278703"  # 177chart


def _encrypt(public_key_b64: str, value: str) -> str:
    """GitHub Secrets 用に libsodium sealed box で暗号化して base64 で返す。"""
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk)
    enc = sealed.encrypt(value.encode("utf-8"))
    return base64.b64encode(enc).decode("utf-8")


def _update_secret(api: str, headers: dict, secret_name: str, value: str, key: str, key_id: str) -> None:
    enc = _encrypt(key, value)
    put = requests.put(
        f"{api}/{secret_name}",
        headers=headers,
        json={"encrypted_value": enc, "key_id": key_id},
        timeout=60,
    )
    put.raise_for_status()
    print(f"[OK] Secret {secret_name} updated (HTTP {put.status_code})")


def main() -> None:
    user_token = os.environ.get("INSTAGRAM_USER_TOKEN", "").strip()
    app_id = os.environ.get("META_APP_ID", "").strip()
    app_secret = os.environ.get("META_APP_SECRET", "").strip()
    page_id = os.environ.get("INSTAGRAM_PAGE_ID", DEFAULT_PAGE_ID).strip()
    gh_pat = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()

    if not user_token or not app_id or not app_secret:
        print("[ERR] INSTAGRAM_USER_TOKEN / META_APP_ID / META_APP_SECRET 未設定")
        sys.exit(1)
    if not gh_pat or not repo:
        print("[ERR] GH_PAT / GITHUB_REPOSITORY 未設定")
        sys.exit(1)

    # 1. ユーザートークンを延長（新しい60日トークン）
    try:
        r = requests.get(
            "https://graph.facebook.com/v21.0/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": user_token,
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        new_user_token = data["access_token"]
        print(f"[OK] Instagram user token refreshed (expires_in={data.get('expires_in')})")
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] user token refresh failed: {e} {body}")
        print("      → トークンが既に失効している可能性。Graph API Explorerで手動再発行してください。")
        sys.exit(1)

    # 2. ページアクセストークンを再取得（投稿にはこちらを使う）
    try:
        r2 = requests.get(
            "https://graph.facebook.com/v21.0/me/accounts",
            params={"fields": "id,name,access_token", "access_token": new_user_token},
            timeout=60,
        )
        r2.raise_for_status()
        pages = r2.json().get("data", [])
        page = next((p for p in pages if p.get("id") == page_id), None)
        if not page:
            print(f"[ERR] page id={page_id} が /me/accounts の結果に見つかりません")
            sys.exit(1)
        new_page_token = page["access_token"]
        print(f"[OK] Page token fetched (page={page.get('name')})")
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] page token fetch failed: {e} {body}")
        sys.exit(1)

    # 3. リポジトリの公開鍵を取得してSecretsを更新
    api = f"https://api.github.com/repos/{repo}/actions/secrets"
    headers = {
        "Authorization": f"Bearer {gh_pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        pk = requests.get(f"{api}/public-key", headers=headers, timeout=60)
        pk.raise_for_status()
        key = pk.json()["key"]
        key_id = pk.json()["key_id"]
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] public-key 取得失敗（GH_PATの権限を確認）: {e} {body}")
        sys.exit(1)

    try:
        _update_secret(api, headers, "INSTAGRAM_USER_TOKEN", new_user_token, key, key_id)
        _update_secret(api, headers, "INSTAGRAM_ACCESS_TOKEN", new_page_token, key, key_id)
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] Secret更新失敗: {e} {body}")
        sys.exit(1)

    print("=== Instagram token refresh done ===")


if __name__ == "__main__":
    main()
