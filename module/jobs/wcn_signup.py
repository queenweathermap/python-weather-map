# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/wcn_signup.py
#
# WCN復旧までの暫定公開: Notionの申込フォーム(DB)の回答を、購読者DBへ Status=wcn で登録する。
#   申込DB   : 状態 が空 または「未処理」 かつ 同意 ON の行を処理
#   結果     : 状態 = 登録済み / 重複(既に会員・登録済み) / エラー(メモに理由)
# 購読者DBに同じメールがあれば:
#   active/admin/lifetime/beta → 触らない(重複)  /  canceled → wcn に変更  /  wcn → 重複
#
# 環境変数: NOTION_TOKEN, NOTION_SUBSCRIBERS_DATABASE_ID, NOTION_WCN_APPLICATIONS_DATABASE_ID
# 復旧後: 購読者DBで Status=wcn を canceled にまとめて変更し、申込DBの回答を削除する。
# =============================================================================

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import List, Optional

import requests

from module.utils.notion_subscribers import API_BASE, _headers, _raise_with_body, _resolve_data_source_id

APP_DB = os.getenv("NOTION_WCN_APPLICATIONS_DATABASE_ID", "9160e4c1e7ff4efea0543c18f1945574").strip()
SUB_DB = os.getenv("NOTION_SUBSCRIBERS_DATABASE_ID", "").strip()
KEEP = ("active", "admin", "lifetime", "beta")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _post(path: str, body: dict) -> dict:
    r = requests.post(f"{API_BASE}/{path}", headers=_headers(), json=body, timeout=30)
    _raise_with_body(r)
    return r.json()


def _patch(path: str, body: dict) -> dict:
    r = requests.patch(f"{API_BASE}/{path}", headers=_headers(), json=body, timeout=30)
    _raise_with_body(r)
    return r.json()


def _text(prop: dict) -> str:
    items = prop.get("title") or prop.get("rich_text") or []
    return "".join(x.get("plain_text", "") for x in items).strip()


def _pending(ds: str) -> List[dict]:
    body = {"filter": {"or": [
        {"property": "状態", "select": {"is_empty": True}},
        {"property": "状態", "select": {"equals": "未処理"}},
    ]}, "page_size": 100}
    return _post(f"data_sources/{ds}/query", body).get("results", [])


def _find_subscriber(ds: str, email: str) -> Optional[dict]:
    res = _post(f"data_sources/{ds}/query", {"filter": {"property": "Email", "rich_text": {"equals": email}}, "page_size": 5}).get("results", [])
    return res[0] if res else None


def _mark(page_id: str, state: str, memo: str = "") -> None:
    props = {"状態": {"select": {"name": state}}}
    if memo:
        props["メモ"] = {"rich_text": [{"text": {"content": memo[:1900]}}]}
    _patch(f"pages/{page_id}", {"properties": props})


def main() -> None:
    if not SUB_DB:
        raise SystemExit("[ERR] NOTION_SUBSCRIBERS_DATABASE_ID 未設定")
    app_ds = _resolve_data_source_id(APP_DB)
    sub_ds = _resolve_data_source_id(SUB_DB)
    rows = _pending(app_ds)
    print(f"[INFO] 未処理の申込 {len(rows)} 件")
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        pid, p = row["id"], row["properties"]
        name = _text(p.get("お名前", {}))
        email = ((p.get("メールアドレス") or {}).get("email") or "").strip().lower()
        try:
            if not (p.get("同意") or {}).get("checkbox"):
                _mark(pid, "エラー", "同意が未チェック")
            elif not EMAIL_RE.match(email):
                _mark(pid, "エラー", "メールアドレスの形式が不正")
            else:
                sub = _find_subscriber(sub_ds, email)
                if sub is None:
                    _post("pages", {"parent": {"data_source_id": sub_ds}, "properties": {
                        "名前": {"title": [{"text": {"content": name or email}}]},
                        "Email": {"rich_text": [{"text": {"content": email}}]},
                        "Status": {"select": {"name": "wcn"}},
                        "Joined At": {"date": {"start": now}},
                    }})
                    _mark(pid, "登録済み", "新規登録")
                    print(f"[OK] 新規登録 {email}")
                else:
                    cur = ((sub["properties"].get("Status") or {}).get("select") or {}).get("name", "")
                    if cur in KEEP or cur == "wcn":
                        _mark(pid, "重複", f"購読者DBに既にあり(Status={cur})")
                        print(f"[SKIP] {email} Status={cur}")
                    else:
                        _patch(f"pages/{sub['id']}", {"properties": {"Status": {"select": {"name": "wcn"}}}})
                        _mark(pid, "登録済み", f"既存行(Status={cur or '空'})をwcnに変更")
                        print(f"[OK] 既存行をwcnへ {email}")
        except Exception as e:  # 1件の失敗で全体を止めない
            print(f"[ERR] {email}: {e}")
            try:
                _mark(pid, "エラー", str(e)[:300])
            except Exception:
                pass
    print("=== Done ===")
