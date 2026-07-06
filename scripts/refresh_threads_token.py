# -*- coding: utf-8 -*-
# =============================================================================
# scripts/refresh_threads_token.py
#
# Threads 長期アクセストークンを自動延長し、GitHub Secret を更新する。
#
#   1. graph.threads.net/refresh_access_token で新しい60日トークンを取得
#   2. リポジトリの公開鍵で暗号化し、Secret THREADS_ACCESS_TOKEN を上書き
#
# 必要な環境変数:
#   THREADS_ACCESS_TOKEN   現在の長期トークン（Secretから）
#   GH_PAT                 細粒度PAT（このリポジトリの Secrets: Read and write 権限）
#   GITHUB_REPOSITORY      "owner/repo"（GitHub Actionsが自動で付与）
#
# 任意:
#   THREADS_SECRET_NAME    更新するSecret名（既定: THREADS_ACCESS_TOKEN）
# =============================================================================

from __future__ import annotations

import base64
import os
import sys

import requests
from nacl import encoding, public


def _encrypt(public_key_b64: str, value: str) -> str:
    """GitHub Secrets 用に libsodium sealed box で暗号化して base64 で返す。"""
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk)
    enc = sealed.encrypt(value.encode("utf-8"))
    return base64.b64encode(enc).decode("utf-8")


def main() -> None:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    gh_pat = os.environ.get("GH_PAT", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    secret_name = os.environ.get("THREADS_SECRET_NAME", "THREADS_ACCESS_TOKEN").strip()

    if not token:
        print("[ERR] THREADS_ACCESS_TOKEN 未設定")
        sys.exit(1)
    if not gh_pat or not repo:
        print("[ERR] GH_PAT / GITHUB_REPOSITORY 未設定")
        sys.exit(1)

    # 1. トークンを延長（新しい60日トークン）
    try:
        r = requests.get(
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": token},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        new_token = data["access_token"]
        print(f"[OK] Threads token refreshed (expires_in={data.get('expires_in')})")
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] refresh failed: {e} {body}")
        print("      → トークンが既に失効している可能性。ユーザートークン生成ツールで手動再発行してください。")
        sys.exit(1)

    # 2. リポジトリの公開鍵を取得
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

    # 3. 暗号化してSecretを更新（PUT）
    try:
        enc = _encrypt(key, new_token)
        put = requests.put(
            f"{api}/{secret_name}",
            headers=headers,
            json={"encrypted_value": enc, "key_id": key_id},
            timeout=60,
        )
        put.raise_for_status()
        print(f"[OK] Secret {secret_name} updated (HTTP {put.status_code})")
    except Exception as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[ERR] Secret更新失敗: {e} {body}")
        sys.exit(1)

    print("=== Threads token refresh done ===")


if __name__ == "__main__":
    main()
