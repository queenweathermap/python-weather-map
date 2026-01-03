# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を
# GitHub Actions 上で自動取得し、モデル別にメール送信する（GSM/MSM/LFMで計3通）。
#
# ✅方針
# - 取得元：tgv の PNG
# - 送信：PNG→JPGに変換して「個別添付」
# - GSM / MSM / LFM それぞれ別メール（合計3通）
# - INITは固定せず「存在するRJTD（init）」を自動探索
# - FTは複数枚取得（まずGSMだけ伸ばす→次にMSM→LFM の運用に対応）
# - 失敗(401/403/404など)は Slack に要点ログ（設定があれば）
#
# ✅認証
#   1) JMA_ADV_USER / JMA_ADV_PASS → Authorization: Basic を生成（推奨）
#   2) JMA_AUTH_BASIC（"Basic xxx"）をそのまま使う（フォールバック）
#
# ✅環境変数（例）
#   MAIL_TO / TO_EMAIL               : 送信先（mail_utils の仕様に合わせる）
#   MAIL_SUBJECT_PREFIX              : 件名プレフィックス（default "JMA"）
#   JPG_QUALITY                      : JPG品質（default 85）
#   GSM_MAX_FT / GSM_FT_STEP         : default 27 / 3
#   MSM_MAX_FT / MSM_FT_STEP         : default 0  / 1
#   LFM_MAX_FT / LFM_FT_STEP         : default 0  / 1
#   SLACK_BOT_TOKEN / SLACK_CHANNEL_ID: Slack通知（あれば）
#
# ✅依存
# - requests
# - pillow
# - module.utils.mail_utils.send_mail
# - module.utils.slack_utils.send_slack_text
# =============================================================================

# --- GitHub Actions / 直叩き実行でも module/ を import できるようにする ---
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
# -----------------------------------------------------------------------------

import os
import io
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image

from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text


# =============================================================================
# env utils
# =============================================================================
def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


# =============================================================================
# auth
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
# slack
# =============================================================================
def slack_enabled() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN")) and bool(os.getenv("SLACK_CHANNEL_ID"))


def slack_notify(text: str) -> None:
    if not slack_enabled():
        return
    try:
        channel = os.getenv("SLACK_CHANNEL_ID", "")
        send_slack_text(channel=channel, message=text)
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


# =============================================================================
# http headers
# =============================================================================
def headers_for(url: str, referer: str) -> dict:
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# =============================================================================
# image convert
# =============================================================================
def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int = 85) -> bytes:
    with Image.open(io.BytesIO(png_bytes)) as im:
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im2 = bg
        else:
            im2 = im.convert("RGB")

        out = io.BytesIO()
        im2.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()


# =============================================================================
# url rules (IMPORTANT)
# =============================================================================
def fmt_rjtd(init_dt_utc: datetime) -> str:
    """
    RJTD = DDHHMM (UTC), minute is typically 00
    例：03日06:00UTC -> "030600"
    """
    dt = init_dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int) -> datetime:
    dt = dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(base_view: str, ft_hours: int) -> str:
    """
    ✅あなたの提示例に合わせる：
      FT=0 -> VIEW....000
      FT=3 -> VIEW....003
      FT=6 -> VIEW....006
    つまり「idx = ft/step で +1」ではなく、基本は「+ ft_hours」。

    base_view は "3102000" や "500200" など（数値文字列）
    """
    return str(int(base_view) + int(ft_hours))


# =============================================================================
# model definition
# =============================================================================
@dataclass
class Item:
    label: str
    layer: str
    view_candidates: List[str]  # base view candidates for FT=0 (200/201揺れなど)
    jpg_prefix: str


@dataclass
class ModelCfg:
    base: str
    referer: str
    init_step_hours: int        # init探索の刻み（GSM=3h, MSM/LFM=1h想定）
    ft_list: List[int]          # 0..max
    items: List[Item]


def build_ft_list(max_ft: int, step: int) -> List[int]:
    if max_ft < 0:
        return [0]
    return list(range(0, max_ft + 1, step))


def load_model_groups() -> Dict[str, ModelCfg]:
    # まずはGSMだけ伸ばす→次にMSM→LFM の運用
    gsm_max  = env_int("GSM_MAX_FT", 27)
    gsm_step = env_int("GSM_FT_STEP", 3)

    msm_max  = env_int("MSM_MAX_FT", 0)
    msm_step = env_int("MSM_FT_STEP", 1)

    lfm_max  = env_int("LFM_MAX_FT", 0)
    lfm_step = env_int("LFM_FT_STEP", 1)

    return {
        "GSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/GSMWide",
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            init_step_hours=3,
            ft_list=build_ft_list(gsm_max, gsm_step),  # 0,3,6,...,27
            items=[
                Item(label="300hPa",   layer="300",  view_candidates=["3002000"], jpg_prefix="GSM_300"),
                Item(label="300hPa-2", layer="3002", view_candidates=["3102000"], jpg_prefix="GSM_3002"),
            ],
        ),
        "MSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/MSMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=1,
            ft_list=build_ft_list(msm_max, msm_step),  # まずは [0]
            items=[
                Item(label="500hPa",   layer="500",  view_candidates=["500200"],  jpg_prefix="MSM_500"),
                Item(label="500hPa-2", layer="5002", view_candidates=["510200"],  jpg_prefix="MSM_5002"),
                Item(label="700hPa",   layer="700",  view_candidates=["700200"],  jpg_prefix="MSM_700"),
            ],
        ),
        "LFM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/LFMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=1,
            ft_list=build_ft_list(lfm_max, lfm_step),  # まずは [0]
            items=[
                Item(label="850hPa",   layer="850",  view_candidates=["850200", "850201"], jpg_prefix="LFM_850"),
                Item(label="850hPa-2", layer="8502", view_candidates=["860200", "860201"], jpg_prefix="LFM_8502"),
                Item(label="925hPa",   layer="925",  view_candidates=["920200", "920201"], jpg_prefix="LFM_925"),
                Item(label="975hPa",   layer="975",  view_candidates=["970200", "970201"], jpg_prefix="LFM_975"),
                Item(label="sfc",      layer="sfc",  view_candidates=["000200", "000201"], jpg_prefix="LFM_sfc"),
                Item(label="sfc-2",    layer="sfc2", view_candidates=["010200", "010201"], jpg_prefix="LFM_sfc2"),
            ],
        ),
    }


# =============================================================================
# init probing
# =============================================================================
def find_working_init_dt(model_name: str, cfg: ModelCfg, *, max_back_hours: int = 72) -> datetime:
    """
    いまのUTCから遡って「FT=0 の代表画像が200になる init」を探す
    - GSMは3h刻み、MSM/LFMは1h刻みで遡る想定
    """
    step = cfg.init_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step)

    it0 = cfg.items[0]
    layer0 = it0.layer

    # 代表は候補を順に試す（200/201揺れを吸収）
    view0_candidates = it0.view_candidates

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
        rjtd = fmt_rjtd(init_dt)

        for base_view in view0_candidates:
            test_url = build_png_url(cfg.base, layer0, base_view, rjtd)

            try:
                r = requests.get(test_url, headers=headers_for(test_url, cfg.referer), timeout=25)
                if r.status_code == 200:
                    print(f"[OK] {model_name} init found: {init_dt.isoformat()} (RJTD_{rjtd}) url={test_url}")
                    return init_dt

                if r.status_code in (401, 403):
                    raise RuntimeError(f"{model_name} auth error HTTP {r.status_code} at {test_url}")

                # 404などは次の候補/時刻へ
                print(f"[NG] {model_name} init RJTD_{rjtd} HTTP {r.status_code} url={test_url}")

            except Exception as e:
                print(f"[ERR] {model_name} init probe failed: {type(e).__name__}: {e}")

    raise RuntimeError(f"{model_name}: init not found within back={max_back_hours}h")


# =============================================================================
# fetch / run
# =============================================================================
Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def fetch_png(url: str, referer: str) -> Tuple[int, bytes, str]:
    r = requests.get(url, headers=headers_for(url, referer), timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def run_model(model_name: str, cfg: ModelCfg, init_dt: datetime) -> Tuple[List[Attachment], List[str]]:
    jpg_quality = env_int("JPG_QUALITY", 85)

    attachments: List[Attachment] = []
    errors: List[str] = []

    # ✅ RJTDは init 固定（FTで動かさない）
    rjtd = fmt_rjtd(init_dt)

    for it in cfg.items:
        for ft in cfg.ft_list:
            ok = False
            last_status: Optional[int] = None

            for base_view in it.view_candidates:
                # ✅ FT=3なら +3、FT=6なら +6（あなたの提示規則）
                view_code = view_for_ft(base_view, ft)
                url = build_png_url(cfg.base, it.layer, view_code, rjtd)

                try:
                    status, content, ctype = fetch_png(url, cfg.referer)
                    last_status = status

                    if status == 200:
                        if "text/html" in (ctype or "") or content[:20].lower().startswith(b"<!doctype html"):
                            errors.append(f"[{model_name}] {it.label} ft={ft}: got HTML (auth?) url={url}")
                            break

                        jpg = png_bytes_to_jpg_bytes(content, quality=jpg_quality)
                        fname = f"{it.jpg_prefix}_ft{ft:03d}.jpg"
                        attachments.append((fname, jpg, "image/jpeg"))
                        print(f"[OK] {model_name} {it.label} ft={ft} url={url}")
                        ok = True
                        break

                    if status in (401, 403):
                        errors.append(f"[{model_name}] {it.label} ft={ft}: HTTP{status} auth/forbidden url={url}")
                        break

                    if status == 404:
                        continue

                    errors.append(f"[{model_name}] {it.label} ft={ft}: HTTP{status} url={url}")

                except Exception as e:
                    errors.append(f"[{model_name}] {it.label} ft={ft}: {type(e).__name__}: {e} url={url}")

            if not ok:
                errors.append(f"[{model_name}] {it.label} ft={ft}: failed (last HTTP{last_status})")

    return attachments, errors


# =============================================================================
# mail (per model)
# =============================================================================
def send_model_mail(model_name: str, init_dt: datetime, atts: List[Attachment], errors: List[str]) -> None:
    prefix = os.getenv("MAIL_SUBJECT_PREFIX", "JMA").strip()
    mail_to = (os.getenv("MAIL_TO") or os.getenv("TO_EMAIL") or "").strip()

    init_str = init_dt.strftime("%d %H:00(UTC)")
    subject = f"{prefix} ADV TGV {model_name} RJTD={fmt_rjtd(init_dt)} (init {init_str})"

    body = "\n".join([
        f"JMA 防災情報アドバイザー向け 専門天気図（tgv）: {model_name}",
        f"RJTD (init): {fmt_rjtd(init_dt)}  / {init_str}",
        "",
        f"files: {len(atts)}",
        f"errors: {len(errors)}",
        "",
        "※ 個人利用・非公開",
        "※ GitHub Actions 実行",
    ])

    if not mail_to:
        raise RuntimeError("MAIL_TO (or TO_EMAIL) is empty")

    send_mail(
        to_addrs=mail_to,
        subject=subject,
        body=body,
        attachment_blobs=atts,   # ✅ JPG個別添付
        slack_mode="off",        # Slackはこのスクリプト側で投げる
    )

    print(f"[OK] {model_name} mail sent: to={mail_to} files={len(atts)} errors={len(errors)}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")
    groups = load_model_groups()

    for model_name in ("GSM", "MSM", "LFM"):
        cfg = groups[model_name]
        print(f"\n--- Fetch group: {model_name} ({len(cfg.items)} items) ---")

        # INIT探索
        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=72)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)
            continue

        # 取得
        atts, errors = run_model(model_name, cfg, init_dt)

        # 取得ゼロは致命的：Slack
        if not atts:
            msg = (
                f"❌ ADV TGV {model_name}: no images fetched\n"
                f"RJTD={fmt_rjtd(init_dt)} init={init_dt.isoformat()}\n"
                + ("\n".join(errors[:40]) if errors else "(no detail)")
            )
            print(msg)
            slack_notify(msg)
            continue

        # エラー要約はSlack（多すぎるので先頭だけ）
        if errors:
            msg = (
                f"⚠️ ADV TGV {model_name}: fetch errors ({len(errors)})\n"
                f"RJTD={fmt_rjtd(init_dt)} init={init_dt.strftime('%d %H:00(UTC)')}\n"
                + "\n".join(errors[:60])
            )
            slack_notify(msg)

        # メール送信（モデルごとに1通）
        try:
            send_model_mail(model_name, init_dt, atts, errors)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: mail send failed\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
