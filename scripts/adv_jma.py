# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」PNG を
# GitHub Actions 上で自動取得し、メール（必要ならSlack）で送るスクリプト。
#
# 【このスクリプトの思想】（weathercaster_jma.py に寄せる）
# - 取得→/tmp に保存→ZIP化→メール送信、という流れを踏襲
# - メール送信は module.utils.mail_utils.send_mail を利用（587=STARTTLS対応）
# - Safari で観測した「Authorization + Referer」を再現して取得
# - 404（生成遅延/時刻ズレ/VIEW****200-201揺れ）に強い：
#    1) 404 のときは「待ってリトライ」（生成待ち対策）
#    2) VIEW****200/201 の揺れを入替えて再取得
#    3) それでも無ければ RJTD_****** の時刻を「少し前」に戻して探索
#
# 【認証の扱い（重要）】
# 優先順位：
#   1) JMA_ADV_USER / JMA_ADV_PASS から毎回 Basic を生成（推奨）
#   2) フォールバックとして JMA_AUTH_BASIC（"Basic xxxx"）をそのまま使用
#
# 【Secrets / env（GitHub Actions）想定】
# - JMA_ADV_USER / JMA_ADV_PASS（推奨）
# - JMA_AUTH_BASIC（予備：Safariで観測した Authorization: Basic... をそのまま）
#
# - FROM_EMAIL, TO_EMAIL, SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
# - MAIL_SUBJECT_PREFIX（任意。mail_utils が参照）
# - SMTP_STARTTLS（任意。587なら通常 1）
# - MAIL_DEBUG（任意。1でSMTPデバッグ）
# - SLACK_BOT_TOKEN, SLACK_CHANNEL_ID（任意。Slack通知する場合）
#
# =============================================================================

# --- GitHub Actions / 直叩き実行でも module/ を import できるようにする ---
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # scripts/ の1つ上 = リポジトリ直下
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# ---------------------------------------------------------------------------

import os
import re
import time
import base64
import shutil
from datetime import datetime
from typing import List, Dict, Optional

import requests

from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text


# =============================================================================
# 取得したいPNGの定義
# =============================================================================
# ここは「固定」でOK（まずは安定運用優先）。
# 将来的に「最新時刻を自動で追う」場合は、別途ロジック化します。
#
# 重要：
# - URLは “Safariのネットワーク” で実際に取れているものが最も確実
# - LFM は生成タイミングがズレて 404 になりやすいので、下のフォールバックが効く
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
        # ここは 200/201 が揺れやすい・生成遅延も起きやすい
        "url": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow/850/images/VIEW860201_RJTD_030600.png",
        "filename": "LFMNarrow_850hPa.png",
    },
]


# =============================================================================
# env ユーティリティ（設定漏れ早期検知）
# =============================================================================
def must_env(name: str) -> str:
    """
    必須の環境変数が未設定なら即エラーにして止める。
    GitHub Actions の Secrets 設定漏れを早期に検知するため。
    """
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


# =============================================================================
# 認証：Basic生成（優先：JMA_ADV_USER/PASS）
# =============================================================================
def make_basic_auth(user: str, password: str) -> str:
    """
    user:password を base64 して Authorization ヘッダ値を作る。
    例: "Basic YWR2..."
    """
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    """
    認証情報の用意（優先順位つき）

      1) JMA_ADV_USER / JMA_ADV_PASS があれば、そこから生成（推奨）
      2) なければ JMA_AUTH_BASIC をそのまま使う（フォールバック）

    Secrets に改行が混ざると認証が壊れるので strip() で吸収。
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")

    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())

    return must_env("JMA_AUTH_BASIC").strip()


# =============================================================================
# Referer：Safariで観測した値に合わせる（重要）
# =============================================================================
def referer_for(url: str) -> str:
    """
    Safariで観測された Referer をモデル別に合わせる。
    Referer 不一致が 401/403 の要因になることがある。
    """
    if "/tgv/data/GSMWide/" in url:
        return "https://www.jma.go.jp/bosai/tgv/GSM/"
    if "/tgv/data/MSMNarrow/" in url:
        return "https://www.jma.go.jp/bosai/tgv/MSM/"
    if "/tgv/data/LFMNarrow/" in url:
        return "https://www.jma.go.jp/bosai/tgv/LFM/"
    return "https://www.jma.go.jp/bosai/tgv/"


def headers_for(url: str) -> dict:
    """
    Safari互換のヘッダを作る。
    - Authorization は get_auth_basic() で統一
    - Referer は URLごとに切替
    - Cache-Control/Pragma はキャッシュ差の挙動ブレを避けたい時に有効
    """
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer_for(url),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# =============================================================================
# 404対策：VIEW****200/201揺れ
# =============================================================================
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

    # 汎用：最初に見つかった 200_ / 201_ を入れ替える（誤爆しにくい範囲）
    if "200_" in url:
        return url.replace("200_", "201_", 1)
    if "201_" in url:
        return url.replace("201_", "200_", 1)

    return None


# =============================================================================
# 404対策：RJTD_****** の「時刻コード」を戻す（生成遅れ・更新タイミング差）
# =============================================================================
_RJTD_RE = re.compile(r"(RJTD_)(\d{6})(\.png)$")


def backoff_timecode(url: str, steps: int = 1) -> Optional[str]:
    """
    RJTD_****** の6桁を steps 回だけ -100 する（例：030600->030500）。
    ※ここは「あなたが観測している命名規則（030600→030500）」に合わせた単純減算。
      実際の意味が HHMMSS でないとしても、"ひとつ前のコマ" を探すのに効く。
    """
    m = _RJTD_RE.search(url)
    if not m:
        return None

    n = int(m.group(2))
    n2 = n - 100 * steps
    if n2 < 0:
        return None

    new_code = f"{n2:06d}"
    return _RJTD_RE.sub(rf"\1{new_code}\3", url)


# =============================================================================
# HTTP GET（404生成待ちリトライ）
# =============================================================================
def get_once(url: str) -> requests.Response:
    return requests.get(url, headers=headers_for(url), timeout=30)


def get_with_retry(url: str, *, retries: int = 8, sleep_sec: int = 20) -> requests.Response:
    """
    404 の時だけ待ってリトライする。
    - 401/403 は認証/Referer の問題 → 待っても直らないので即raise
    """
    last = None
    for i in range(retries + 1):
        r = get_once(url)
        last = r

        # 認証系は即エラー（待っても直らない）
        if r.status_code in (401, 403):
            r.raise_for_status()

        # 404以外 → 成功or別エラー
        if r.status_code != 404:
            r.raise_for_status()
            return r

        # 404 → 生成待ちの可能性。最後の試行なら返す（上位で判断）
        if i == retries:
            return r

        print(f"  404 Not Found (try {i+1}/{retries}) wait {sleep_sec}s: {url}")
        time.sleep(sleep_sec)

    return last  # 型の都合（通常到達しない）


# =============================================================================
# 取得（フォールバック付き）
# =============================================================================
def get_with_fallback(url: str) -> requests.Response:
    """
    1) 指定URLを 404待ちリトライ込みで取得
    2) それでも404なら 200/201 入替を試す
    3) それでも404なら RJTD時刻を少し前へずらして探索（＋200/201も併用）
    """
    # 1) まずは指定URL（生成待ちリトライ）
    r = get_with_retry(url, retries=8, sleep_sec=20)
    if r.status_code != 404:
        return r

    # 2) 200/201 揺れ
    alt = make_alt_url_if_possible(url)
    if alt:
        print(f"  still 404. Try alternate 200/201: {alt}")
        r2 = get_with_retry(alt, retries=6, sleep_sec=20)
        if r2.status_code != 404:
            return r2

    # 3) 時刻を戻して探索（最大6コマ戻す：030600→030000 くらい）
    for step in range(1, 7):
        back = backoff_timecode(url, steps=step)
        if not back:
            break

        print(f"  still 404. Try earlier time (step={step}): {back}")
        r3 = get_with_retry(back, retries=3, sleep_sec=15)
        if r3.status_code != 404:
            return r3

        back_alt = make_alt_url_if_possible(back)
        if back_alt and back_alt != back:
            print(f"  try earlier time + 200/201: {back_alt}")
            r4 = get_with_retry(back_alt, retries=3, sleep_sec=15)
            if r4.status_code != 404:
                return r4

    # ここまで来たら「本当に無い」ので例外化してジョブを落とす
    r.raise_for_status()
    return r


# =============================================================================
# PNG取得：/tmp 配下に保存
# =============================================================================
def fetch_images_to_tmp(out_dir: Path) -> List[Path]:
    """
    MAPS に定義された PNG を取得し、out_dir に保存して返す。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    for m in MAPS:
        title = m["title"]
        url = m["url"]
        fname = m["filename"]

        print(f"Fetching: {title}")
        resp = get_with_fallback(url)

        # Content-Type軽チェック：HTMLを拾った時の保険（認証失敗など）
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "image" not in ctype:
            print(f"[WARN] unexpected content-type: {ctype} url={url}")

        path = out_dir / fname
        path.write_bytes(resp.content)
        saved.append(path)

    return saved


# =============================================================================
# Slack通知（任意）
# =============================================================================
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


# =============================================================================
# メール送信：mail_utils を利用（ZIP添付に統一して安定させる）
# =============================================================================
def send_result_mail(out_dir: Path, files: List[Path]) -> None:
    """
    /tmp に保存された PNG 一式を ZIP 化して送る。
    """
    # mail_utils 側は MAIL_SUBJECT_PREFIX を参照するので、ここは素直にsubjectを作る
    subject_prefix = os.getenv("MAIL_SUBJECT_PREFIX") or os.getenv("EMAIL_SUBJECT_PREFIX") or "JMA"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"{subject_prefix} 専門天気図（tgv） {now}"

    body = (
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）を自動取得しました。\n"
        "・個人利用・非公開\n"
        "・GitHub Actions 実行\n"
        "\n"
        "添付：PNG一式（ZIP）\n"
    )

    # ZIP化（zip_utils の既存関数を利用）
    zip_name = f"tgv_maps_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    zip_bytes = to_zip_bytes_from_dir(str(out_dir))

    # mail_utils に blob添付で渡す（名前, bytes, content-type）
    # 587/STARTTLS は mail_utils が処理する（SMTP_STARTTLS=1 が既定）
    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=[(zip_name, zip_bytes, "application/zip")],
        is_html=False,
        slack_mode="off",  # mail_utils のSlack同報は今回は使わない（使うなら "error_only" 等）
    )


# =============================================================================
# main
# =============================================================================
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

    # メール送信（FROM/TO/SMTPが未設定なら mail_utils が例外で止める＝設定漏れ検知）
    send_result_mail(out_dir, files)
    print("=== Mail sent successfully ===")

    # Slack（任意）
    slack_notify(f"✅ tgv maps sent: {', '.join([p.name for p in files])}")


if __name__ == "__main__":
    main()
