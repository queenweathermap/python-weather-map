# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」PNGを
# GitHub Actions 上で自動取得し、メール/Slack で送る。
#
# - Safari で観測した Authorization / Referer を再現して取得する
# - 画像は /tmp に書き出して扱う（Actionsで安全、後始末しやすい）
# - 404（VIEW****200/201揺れ）にフォールバック
# - メール送信は module.utils.mail_utils.send_mail を使う（587=STARTTLS対応）
# - 添付は既定で ZIP（MAIL_ATTACH_AS_ZIP=1 推奨）
#   ※ mail_utils 側の仕様：サイズ超過や設定により自動ZIPも可能
# =============================================================================

import os
import shutil
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import base64

import requests

from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text


# -----------------------------------------------------------------------------
# 取得したい PNG の定義
# -----------------------------------------------------------------------------
# ここは「あなたが送りたい図」に合わせて固定でOK。
# （時刻の部分を動的にしたい場合は、別途ロジックを追加する）
MAPS: List[Dict[str, str]] = [
    {
        "title": "GSMWide 300hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/GSMWide/300/images/VIEW3002003_RJTD_030000.png",
        "filename": "GSMWide_300hPa.png",
    },
    {
        "title": "MSMNarrow 700hPa",
        "url": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow/700/images/VIEW700201_RJTD_030300.png",
        "filename": "MSMNarrow_700hPa.png",
    },
    {
        "title": "LFMNarrow 850hPa",
        # LFMは200/201が揺れることがある → 404時に自動で入替を試す
        "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW860201_RJTD_030600.png",
        "filename": "LFMNarrow_850hPa.png",
    },
]


# -----------------------------------------------------------------------------
# 環境変数ユーティリティ（weathercasterと同じ「設定漏れ早期検知」思想）
# -----------------------------------------------------------------------------
def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


# -----------------------------------------------------------------------------
# 認証：JMA_ADV_USER / JMA_ADV_PASS を正とし、JMA_AUTH_BASIC は予備
# -----------------------------------------------------------------------------
def make_basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    """
    優先順位：
      1) JMA_ADV_USER / JMA_ADV_PASS から毎回生成（推奨）
      2) 予備：JMA_AUTH_BASIC をそのまま利用（Safariで観測した値の退避）
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())

    # フォールバック
    return must_env("JMA_AUTH_BASIC").strip()


# -----------------------------------------------------------------------------
# Referer：Safariで観測した値に合わせる（401/403対策）
# -----------------------------------------------------------------------------
def referer_for(url: str) -> str:
    if "/tgv/data/GSMWide/" in url:
        return "https://www.jma.go.jp/bosai/tgv/GSM/"
    if "/tgv/data/MSMNarrow/" in url:
        return "https://www.jma.go.jp/bosai/tgv/MSM/"
    if "/tgv/data/LFMNarrow/" in url:
        return "https://www.jma.go.jp/bosai/tgv/LFM/"
    return "https://www.jma.go.jp/bosai/tgv/"


def headers_for(url: str) -> dict:
    """
    Safari互換に寄せたヘッダ。
    - Authorization / Referer が重要
    - Cache-Control/Pragma は「キャッシュのせいで挙動が変わる」対策
    """
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer_for(url),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# -----------------------------------------------------------------------------
# 404対策：VIEW****200/201揺れの自動フォールバック
# -----------------------------------------------------------------------------
def make_alt_url_if_possible(url: str) -> Optional[str]:
    """
    例：
      .../VIEW860201_RJTD_030600.png  ->  .../VIEW860200_RJTD_030600.png
      .../VIEW860200_RJTD_030600.png  ->  .../VIEW860201_RJTD_030600.png
    """
    if "VIEW860201_" in url:
        return url.replace("VIEW860201_", "VIEW860200_")
    if "VIEW860200_" in url:
        return url.replace("VIEW860200_", "VIEW860201_")

    # 汎用：最初に出てきた 200_ / 201_ を入れ替える（誤爆しにくい範囲で）
    if "200_" in url:
        return url.replace("200_", "201_", 1)
    if "201_" in url:
        return url.replace("201_", "200_", 1)

    return None


def get_with_fallback(url: str) -> requests.Response:
    """
    通常取得 → 404 のときだけ代替URLを試す。
    401/403は認証/Refererの問題なので代替を試しても無意味 → 即raise。
    """
    r = requests.get(url, headers=headers_for(url), timeout=30)
    if r.status_code != 404:
        r.raise_for_status()
        return r

    alt = make_alt_url_if_possible(url)
    if not alt:
        r.raise_for_status()
        return r

    print(f"  404 Not Found. Try alternate: {alt}")
    r2 = requests.get(alt, headers=headers_for(alt), timeout=30)
    r2.raise_for_status()
    return r2


# -----------------------------------------------------------------------------
# PNG取得：/tmp 配下に保存
# -----------------------------------------------------------------------------
def fetch_images_to_tmp(out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    for m in MAPS:
        title = m["title"]
        url = m["url"]
        fname = m["filename"]

        print(f"Fetching: {title}")
        resp = get_with_fallback(url)

        # Content-Typeの軽いチェック（壊れたHTMLを拾った時の保険）
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "image" not in ctype and not fname.lower().endswith(".png"):
            print(f"[WARN] unexpected content-type: {ctype} for {url}")

        path = out_dir / fname
        path.write_bytes(resp.content)
        saved.append(path)

    return saved


# -----------------------------------------------------------------------------
# Slack通知（任意）
# -----------------------------------------------------------------------------
def slack_notify(message: str) -> None:
    """
    weathercaster と同様に「設定があれば送る」運用に寄せる。
    - SLACK_BOT_TOKEN / SLACK_CHANNEL_ID が無ければ何もしない
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")
    if not (token and channel):
        return
    try:
        send_slack_text(channel=channel, message=message)
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


# -----------------------------------------------------------------------------
# メール送信：mail_utils を利用（ZIP or 複数添付は mail_utils の設定に任せる）
# -----------------------------------------------------------------------------
def send_result_mail(out_dir: Path, files: List[Path]) -> None:
    subject_prefix = os.getenv("MAIL_SUBJECT_PREFIX") or os.getenv("EMAIL_SUBJECT_PREFIX") or "JMA"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"{subject_prefix} 専門天気図（tgv） {now}"

    body = (
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）を自動取得しました。\n"
        "・個人利用・非公開\n"
        "・GitHub Actions 実行\n"
    )

    # 1) 既定は ZIP 添付に寄せる（weathercasterと揃える）
    #    - mail_utils は「添付合計が大きいと自動ZIP」もできるが、
    #      ここで確実にZIPにして送る方が運用が安定する
    zip_name = f"tgv_maps_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    zip_bytes = to_zip_bytes_from_dir(str(out_dir))

    # mail_utils は blob 添付（名前, bytes, content-type）に対応している
    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=[(zip_name, zip_bytes, "application/zip")],
        is_html=False,
        slack_mode="off",  # mail_utilsのSlackは使わない（使うなら "error_only" 等）
    )


# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------
def main() -> None:
    print("=== Start fetching JMA TGV maps (advisor) ===")

    # /tmp を使う（Actionsでもローカルでも安全）
    out_dir = Path("/tmp") / "jma_tgv_maps"
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 画像取得
    files = fetch_images_to_tmp(out_dir)
    print("Fetched:", [p.name for p in files])

    # メール送信（MAIL_TOが無いなら送らない運用にしたければ、ここで分岐）
    # 今は「設定されていれば mail_utils が送る / 無ければ例外」で統一。
    send_result_mail(out_dir, files)
    print("=== Mail sent successfully ===")

    # Slack（任意）
    slack_notify(f"✅ tgv maps sent: {', '.join([p.name for p in files])}")


if __name__ == "__main__":
    main()
