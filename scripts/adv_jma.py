# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を
# GitHub Actions 上で自動取得し、モデル別にメール（3通）で送る。
#
# ✅ 方針（あなたの要件を反映）
# - JMAからは PNG を取得（Authorization / Referer をSafari互換で付与）
# - メール送信は JPG 個別添付（PNGは保存しない）
# - GSM / MSM / LFM それぞれ1通（合計3通）
# - FT（予報時間）をリストで回し、RJTD_ の時刻（mmddhh）を自動生成
# - 404 は VIEW番号揺れ対策（200/201など）や「2系」(3002/8502等)を候補として試行
# - 401/403/404等の失敗は Slack にログ（設定がある場合のみ）
#
# ✅ 重要：module/ を import できるようにする（Actions直叩き対策）
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # scripts/ の1つ上 = リポジトリ直下
sys.path.insert(0, str(REPO_ROOT))

import os
import io
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

import requests
from PIL import Image

from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text

# =============================================================================
# 0) ここだけ編集すれば「増やしていける」設定（dict管理）
# =============================================================================
# URLの構造：
#   https://www.jma.go.jp/bosai/tgv/data/<MODEL>/<LAYER>/images/VIEW<view>_RJTD_<mmddhh>00.png
#
# - <mmddhh> は「有効時刻（UTC）の 月日＋時」
# - 例：01/03 06UTC → "0306" → RJTD_030600
#
# view番号は揺れることがあるので、候補を複数持って順に試します。
# （例：LFMの8502が860200/860201で揺れる、など）
# =============================================================================

MODEL_GROUPS: Dict[str, Dict] = {
    "GSM": {
        "base": "https://www.jma.go.jp/bosai/tgv/data/GSMWide",
        "referer": "https://www.jma.go.jp/bosai/tgv/GSM/",
        # GSMは 0〜27h（3h刻み）
        "ft_list": list(range(0, 28, 3)),  # ← ★カンマを追加
        "items": [
            {"label": "300hPa",   "layer": "300",  "view_candidates": ["3002000"], "jpg_prefix": "GSM_300"},
            {"label": "300hPa-2", "layer": "3002", "view_candidates": ["3102000"], "jpg_prefix": "GSM_3002"},
        ],
    },
    "MSM": {
        "base": "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow",
        "referer": "https://www.jma.go.jp/bosai/tgv/MSM/",
        "ft_list": [0],
        "items": [
            {"label": "500hPa",   "layer": "500",  "view_candidates": ["500200"], "jpg_prefix": "MSM_500"},
            {"label": "500hPa-2", "layer": "5002", "view_candidates": ["510200"], "jpg_prefix": "MSM_5002"},
            {"label": "700hPa",   "layer": "700",  "view_candidates": ["700200"], "jpg_prefix": "MSM_700"},
        ],
    },
    "LFM": {
        "base": "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow",
        "referer": "https://www.jma.go.jp/bosai/tgv/LFM/",
        "ft_list": [0],
        "items": [
            {"label": "850hPa",   "layer": "850",  "view_candidates": ["850200", "850201"], "jpg_prefix": "LFM_850"},
            {"label": "850hPa-2", "layer": "8502", "view_candidates": ["860200", "860201"], "jpg_prefix": "LFM_8502"},
            {"label": "925hPa",   "layer": "925",  "view_candidates": ["920200", "920201"], "jpg_prefix": "LFM_925"},
            {"label": "975hPa",   "layer": "975",  "view_candidates": ["970200", "970201"], "jpg_prefix": "LFM_975"},
            {"label": "sfc",      "layer": "sfc",  "view_candidates": ["000200", "000201"], "jpg_prefix": "LFM_sfc"},
            {"label": "sfc-2",    "layer": "sfc2", "view_candidates": ["010200", "010201"], "jpg_prefix": "LFM_sfc2"},
        ],
    },
}


# =============================================================================
# 1) 環境変数ユーティリティ
# =============================================================================

def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


# =============================================================================
# 2) 認証：JMA_ADV_USER/JMA_ADV_PASS を正、JMA_AUTH_BASIC は予備
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
# 3) Slack（設定がある時だけ送る）
# =============================================================================

def slack_log(text: str) -> None:
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")
    if not (token and channel):
        return
    try:
        send_slack_text(channel=channel, message=text)
    except Exception as e:
        print(f"[WARN] Slack failed: {e}")


# =============================================================================
# 4) 時刻（INIT と FT）
# =============================================================================
# INITは「固定」か「追随」かで考え方が変わりますが、
# まずは “ENVで指定できるようにして、未指定なら現在UTCを使う” で堅くいきます。
#
# INIT_UTC の形式：YYYYMMDDHH（例：2026010306）
# =============================================================================

def parse_init_utc() -> datetime:
    s = os.getenv("INIT_UTC", "").strip()
    if s:
        # YYYYMMDDHH
        return datetime.strptime(s, "%Y%m%d%H").replace(tzinfo=timezone.utc)

    # 未指定なら「今のUTC（分秒を切り捨て）」を使う
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)

def mmddhh(dt_utc: datetime) -> str:
    # RJTD_030600 の "0306" 部分
    return dt_utc.strftime("%m%d%H")

def build_url(base: str, layer: str, view: str, valid_dt_utc: datetime) -> str:
    t = mmddhh(valid_dt_utc) + "00"
    return f"{base}/{layer}/images/VIEW{view}_RJTD_{t}.png"


# =============================================================================
# 5) HTTP取得（Safari互換のHeader）
# =============================================================================

def headers_for(referer: str) -> dict:
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

def fetch_png_with_candidates(urls: List[str], referer: str, timeout=30) -> Tuple[Optional[bytes], Optional[str], Optional[int]]:
    """
    候補URLを順に試し、最初に200になったPNG bytesを返す。
    失敗時は (None, last_url, last_status) を返す。
    """
    last_url = None
    last_status = None

    for u in urls:
        last_url = u
        try:
            r = requests.get(u, headers=headers_for(referer), timeout=timeout)
            last_status = r.status_code

            if r.status_code == 200:
                # 画像じゃないHTMLを掴んだ時の保険
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "image" not in ctype:
                    return None, u, 999
                return r.content, u, 200

            # 認証/権限系は候補を変えても意味が薄いので即打ち切り
            if r.status_code in (401, 403):
                return None, u, r.status_code

            # 404等は次候補へ
            continue

        except Exception as e:
            last_status = -1
            print(f"[ERR] request failed: {u} / {e}")
            continue

    return None, last_url, last_status


# =============================================================================
# 6) PNG→JPG（メール用に軽量化）
# =============================================================================

def png_to_jpg_bytes(png_bytes: bytes, quality: int = 85) -> bytes:
    """
    天気図は線画なので、quality=80〜85 で大きく軽くなることが多い。
    """
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# =============================================================================
# 7) モデル単位で「取得→JPG化→メール送信」
# =============================================================================

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)

def run_model(model_name: str, cfg: Dict, init_dt: datetime) -> None:
    base = cfg["base"]
    referer = cfg["referer"]
    ft_list: List[int] = cfg["ft_list"]
    items: List[Dict] = cfg["items"]

    errors: List[str] = []
    attachments: List[Attachment] = []

    print(f"--- Fetch group: {model_name} ({len(items)} items) ---")

    for ft in ft_list:
        valid_dt = init_dt + timedelta(hours=int(ft))
        tag_time = mmddhh(valid_dt)  # 例: 0306
        for it in items:
            layer = it["layer"]
            view_candidates = it["view_candidates"]
            label = it["label"]
            prefix = it["jpg_prefix"]

            # 候補URLを作る（VIEW揺れ対策）
            urls = [build_url(base, layer, v, valid_dt) for v in view_candidates]

            blob, used_url, status = fetch_png_with_candidates(urls, referer=referer, timeout=30)
            if blob is None:
                msg = f"{model_name} ft={ft} {label}: HTTP={status} url={used_url}"
                print(f"[NG] {msg}")
                errors.append(msg)
                continue

            # JPG化して添付（ファイル名は運用しやすいように統一）
            jpg_quality = int(os.getenv("JPEG_QUALITY", "85"))
            jpg = png_to_jpg_bytes(blob, quality=jpg_quality)
            fname = f"{prefix}_FT{ft:03d}_{tag_time}.jpg"
            attachments.append((fname, jpg, "image/jpeg"))
            print(f"[OK] {model_name} ft={ft} {label} -> {fname}")

    # 失敗ログ（404/401等）はSlackへ（要求どおり）
    if errors:
        slack_log("❌ ADV JMA TGV fetch errors\n" + "\n".join(errors[:40]))

    # 何も取れなかったらメールは送らずに例外（運用的に気づきやすい）
    if not attachments:
        raise RuntimeError(f"{model_name}: no images fetched. see Slack/logs.")

    # メール送信（個別JPG添付）
    # mail_utils の subject_prefix は MAIL_SUBJECT_PREFIX を使うので、ここでは中身だけ整える
    now_jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    subj = f"[{model_name}] tgv {init_dt.strftime('%Y%m%d%H')}Z ({now_jst} JST)"
    body = (
        f"JMA 防災情報アドバイザー向け 専門天気図（tgv）\n"
        f"model={model_name}\n"
        f"init={init_dt.strftime('%Y-%m-%d %H:%MZ')}\n"
        f"files={len(attachments)}\n"
        + ("\n\n--- errors ---\n" + "\n".join(errors) if errors else "")
    )

    msg_id = send_mail(
        subject=subj,
        body=body,
        attachment_blobs=attachments,   # ← ZIPにせず個別添付
        is_html=False,
        slack_mode="error_only",        # ← メール送信失敗だけ mail_utils 側で通知してもOK
    )
    print(f"[OK] {model_name}: mail sent. Message-ID={msg_id}")


# =============================================================================
# main
# =============================================================================

def main() -> None:
    init_dt = parse_init_utc()
    print(f"=== Start ADV JMA TGV === init={init_dt.strftime('%Y-%m-%d %H:%MZ')}")

    # GSM / MSM / LFM を順に実行（3通送る）
    for model_name in ("GSM", "MSM", "LFM"):
        cfg = MODEL_GROUPS[model_name]
        run_model(model_name, cfg, init_dt)

    print("=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
