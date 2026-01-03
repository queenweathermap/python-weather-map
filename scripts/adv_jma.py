# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」PNG を自動取得し、
# GSM / MSM / LFM それぞれ “別メール（合計3通）” で送信する。
#
# 【設計方針】
# - Safari の Network タブで観測した挙動を再現（Authorization + Referer）
# - 画像が増える前提：モデルごとに ZIP でまとめて送る（= 3通）
# - 404/一部欠損があってもジョブ全体を止めない（取れるものだけ送る）
# - メール送信は既存 module.utils.mail_utils.send_mail を利用（587=STARTTLS対応）
#
# 【認証の扱い（重要）】
#   優先 1) JMA_ADV_USER / JMA_ADV_PASS から Basic を生成（推奨）
#   予備 2) JMA_AUTH_BASIC をそのまま使用（Safariで拾った値の退避）
#
# 【注意】
# - .env を GitHub に置くのはNG（漏洩リスク）。Actions Secrets を正にする。
# - URL は “今見えているPNGの直URL” を増やしていく運用が最も確実。
# =============================================================================

# -----------------------------------------------------------------------------
# GitHub Actions / 直叩き実行でも module/ を import できるようにする
# （scripts/ 配下から python scripts/adv_jma.py で動かしてもOKにする）
# -----------------------------------------------------------------------------
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # scripts/ の1つ上 = リポジトリ直下
sys.path.insert(0, str(REPO_ROOT))

# -----------------------------------------------------------------------------
# 標準ライブラリ
# -----------------------------------------------------------------------------
import os
import base64
import shutil
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# -----------------------------------------------------------------------------
# サードパーティ
# -----------------------------------------------------------------------------
import requests

# -----------------------------------------------------------------------------
# 既存モジュール（ここが “揃える” ポイント）
# -----------------------------------------------------------------------------
from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text


# =============================================================================
# 1) ここに “送りたいPNG URL” を追加していく（運用の中心）
# =============================================================================
# - group_key: "GSM" / "MSM" / "LFM" の3つを想定
# - referer: Safariで見えた Referer に合わせる（重要）
# - maps: title はメール本文/ログ用、url は直URL、filename はZIP内の名前
GROUPS: Dict[str, Dict] = {
    "GSM": {
        "label": "GSM",
        "referer": "https://www.jma.go.jp/bosai/tgv/GSM/",
        "maps": [
            # --- GSMWide（例：300hPa + 300hPa-2 など） ---
            {
                "title": "GSMWide 300hPa",
                "url": "https://www.jma.go.jp/bosai/tgv/data/GSMWide/300/images/VIEW3002000_RJTD_030600.png",
                "filename": "GSM_300_VIEW3002000_RJTD_030600.png",
            },
            {
                "title": "GSMWide 300hPa-2",
                "url": "https://www.jma.go.jp/bosai/tgv/data/GSMWide/3002/images/VIEW3102000_RJTD_030600.png",
                "filename": "GSM_3002_VIEW3102000_RJTD_030600.png",
            },
        ],
    },

    "MSM": {
        "label": "MSM",
        "referer": "https://www.jma.go.jp/bosai/tgv/MSM/",
        "maps": [
            # --- MSMNarrow（例：500hPa / 500hPa-2 / 700hPa など） ---
            {
                "title": "MSMNarrow 500hPa",
                "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/500/images/VIEW500200_RJTD_030900.png",
                "filename": "MSM_500_VIEW500200_RJTD_030900.png",
            },
            {
                "title": "MSMNarrow 500hPa-2",
                "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/5002/images/VIEW510200_RJTD_030900.png",
                "filename": "MSM_5002_VIEW510200_RJTD_030900.png",
            },
            {
                "title": "MSMNarrow 700hPa",
                "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/700/images/VIEW700200_RJTD_030900.png",
                "filename": "MSM_700_VIEW700200_RJTD_030900.png",
            },
        ],
    },

    "LFM": {
        "label": "LFM",
        "referer": "https://www.jma.go.jp/bosai/tgv/LFM/",
        "maps": [
            # --- LFMNarrow（例：850/8502/925/975/sfc/sfc-2 など） ---
            {
                "title": "LFMNarrow 850hPa",
                "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW850200_RJTD_031100.png",
                "filename": "LFM_850_VIEW850200_RJTD_031100.png",
            },
            {
                "title": "LFMNarrow 850hPa-2",
                "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/8502/images/VIEW860200_RJTD_031100.png",
                "filename": "LFM_8502_VIEW860200_RJTD_031100.png",
            },
            {
                "title": "LFMNarrow 925hPa",
                "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/925/images/VIEW920200_RJTD_031100.png",
                "filename": "LFM_925_VIEW920200_RJTD_031100.png",
            },
            {
                "title": "LFMNarrow 975hPa",
                "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/975/images/VIEW970200_RJTD_031100.png",
                "filename": "LFM_975_VIEW970200_RJTD_031100.png",
            },
            {
                "title": "LFMNarrow sfc",
                "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/sfc/images/VIEW000200_RJTD_031100.png",
                "filename": "LFM_sfc_VIEW000200_RJTD_031100.png",
            },
            {
                "title": "LFMNarrow sfc-2",
                "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/sfc2/images/VIEW010200_RJTD_031100.png",
                "filename": "LFM_sfc2_VIEW010200_RJTD_031100.png",
            },
        ],
    },
}


# =============================================================================
# 2) 環境変数ユーティリティ（設定漏れの早期検知）
# =============================================================================
def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


# =============================================================================
# 3) 認証：JMA_ADV_USER/PASS → Basic生成、なければ JMA_AUTH_BASIC
# =============================================================================
def make_basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())
    return must_env("JMA_AUTH_BASIC").strip()


# =============================================================================
# 4) リクエストヘッダ（Safari互換）
# =============================================================================
def headers_for(url: str, referer: str) -> Dict[str, str]:
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        # キャッシュの “当たり外れ” を避けたい時に効くことがある
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# =============================================================================
# 5) PNG 取得（“失敗しても止めない” が重要）
# =============================================================================
def fetch_one(url: str, referer: str, timeout: int = 30) -> Tuple[Optional[bytes], Optional[str]]:
    """
    1枚取得する。
    戻り値:
      (bytes, None)  = 成功
      (None, reason) = 失敗（例: "404 Not Found"）
    """
    try:
        r = requests.get(url, headers=headers_for(url, referer), timeout=timeout)
        # 認証系はここが原因なので詳細ログに出したい
        if r.status_code in (401, 403):
            return None, f"{r.status_code} Auth/Forbidden"
        if r.status_code == 404:
            return None, "404 Not Found"
        r.raise_for_status()

        # 画像じゃないもの（HTMLなど）を拾った時の保険
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "image" not in ctype:
            return None, f"Unexpected Content-Type: {ctype}"

        return r.content, None

    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fetch_group(out_dir: Path, group_key: str, group: Dict) -> Tuple[List[Path], List[str]]:
    """
    group（GSM/MSM/LFM）単位でまとめて取得する。
    - 取れるものは保存
    - 取れないものは errors に入れて継続
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Path] = []
    errors: List[str] = []

    referer = group["referer"]
    maps = group["maps"]

    print(f"--- Fetch group: {group_key} ({len(maps)} maps) ---")
    for m in maps:
        title = m["title"]
        url = m["url"]
        filename = m["filename"]

        print(f"Fetching: {title}")
        blob, err = fetch_one(url, referer)

        if blob is None:
            # 404 は “時間がズレてる/差し替わった” ことが多いので、
            # 一応ちょっと待って再試行（CDN反映待ち対策）
            if err == "404 Not Found":
                for i in range(2):  # 追加で2回だけ
                    wait = 10
                    print(f"  404 retry {i+1}/2 wait {wait}s: {url}")
                    time.sleep(wait)
                    blob, err = fetch_one(url, referer)
                    if blob is not None:
                        break

            if blob is None:
                msg = f"[{group_key}] FAIL: {title} | {err} | {url}"
                print(msg)
                errors.append(msg)
                continue  # ←ここが“止めない”ポイント

        path = out_dir / filename
        path.write_bytes(blob)
        saved.append(path)

    return saved, errors


# =============================================================================
# 6) ZIP化 → メール送信（1グループ=1通）
# =============================================================================
def send_group_mail(group_key: str, out_dir: Path, saved_files: List[Path], errors: List[str]) -> None:
    """
    - 画像が1枚も取れなかった場合：
        送らない（運用的に “空メール” が邪魔になりやすい）
      ただし、Slack通知は任意で出す。
    """
    if not saved_files:
        print(f"[{group_key}] No files fetched. Skip sending mail.")
        slack_notify(f"⚠️ {group_key}: 0 files fetched. (check URLs/time) \n" + "\n".join(errors[:20]))
        return

    subject_prefix = (os.getenv("MAIL_SUBJECT_PREFIX") or os.getenv("EMAIL_SUBJECT_PREFIX") or "JMA").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"{subject_prefix} {group_key} 専門天気図（tgv） {now}"

    body_lines = [
        f"JMA 防災情報アドバイザー向け 専門天気図（tgv）を自動取得しました。",
        f"Group: {group_key}",
        f"Fetched: {len(saved_files)} files",
        "",
        "・個人利用・非公開",
        "・GitHub Actions 実行",
    ]
    if errors:
        body_lines += [
            "",
            "---- 取得できなかったもの（抜粋）----",
            *errors[:30],  # 多すぎると読めないので上限
        ]
    body = "\n".join(body_lines)

    # ZIPは “グループ単位” で作る（この out_dir は group専用フォルダ）
    zip_name = f"tgv_{group_key}_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    zip_bytes = to_zip_bytes_from_dir(str(out_dir))

    # 既存 mail_utils を使う（587=STARTTLS も 465 も mail_utils 側で吸収）
    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=[(zip_name, zip_bytes, "application/zip")],
        is_html=False,
        slack_mode="off",  # mail_utils でSlackを使うなら "error_only" 等に
    )

    slack_notify(f"✅ {group_key}: mail sent ({len(saved_files)} files) / errors={len(errors)}")


# =============================================================================
# 7) Slack通知（任意：SLACK_BOT_TOKEN/SLACK_CHANNEL_ID がある時だけ）
# =============================================================================
def slack_notify(message: str) -> None:
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")
    if not (token and channel):
        return
    try:
        send_slack_text(channel=channel, message=message)
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


# =============================================================================
# 8) main：GSM/MSM/LFM を順に処理して “3通” 送る
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA (tgv) ===")

    # 1回の実行の作業場（/tmp が安全）
    base_dir = Path("/tmp") / "adv_jma_tgv"
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)
    base_dir.mkdir(parents=True, exist_ok=True)

    all_errors: List[str] = []

    # GSM/MSM/LFM で3通
    for group_key in ("GSM", "MSM", "LFM"):
        group = GROUPS.get(group_key)
        if not group:
            continue

        group_dir = base_dir / group_key
        saved, errors = fetch_group(group_dir, group_key, group)
        all_errors.extend(errors)

        # 1グループ=1通
        send_group_mail(group_key, group_dir, saved, errors)

    print("=== Done ADV JMA (tgv) ===")

    # 全体まとめ（任意）
    if all_errors:
        print(f"[WARN] total errors: {len(all_errors)}")


if __name__ == "__main__":
    main()
