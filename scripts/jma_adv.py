# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_adv.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を自動取得し、
# “天気図ごと（itemごと）” にメール送信（必須）＋Slack投稿（副系）する。
#
# ✅ 仕様（あなたの現行URL規則に準拠）
# - FT は VIEWコード末尾で表現（RJTDは init 固定）
# - GSM: FT=3..30 (3h) 10枚 / item（Slack 1投稿・メール1通）
# - MSM: FT=1..15(1h) + 18,21,24,27,30 合計20枚 / item（Slack 2投稿・メール1通）
# - LFM: FT=1..18(1h) 18枚 / item（Slack 2投稿(10+8)・メール1通）
# - Slack通知（テキスト）は 401/403 or モデル全滅のみ（404は通知しない）
#
# ✅ 環境変数
# - JMA_ADV_USER / JMA_ADV_PASS  (推奨)   または JMA_AUTH_BASIC ("Basic xxxx")
# - DELIVERY_MODE = email | slack | both  (default: both)
# - SLACK_BOT_TOKEN / SLACK_CHANNEL_ID    (Slack投稿したい場合)
# - SLACK_CHUNK = 10                      (default: 10)
# - JPG_QUALITY = 85                      (default: 85)
# - INIT_SEARCH_HOURS = 72                (default: 72)
# - TGV_USE_AUTH = "0"(default) / "1"     ★公開天気図なら0推奨
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import io
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests
from PIL import Image

from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text, upload_bytes_slack


# =============================================================================
# Types
# =============================================================================
Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


# =============================================================================
# Env utils
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


def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


# =============================================================================
# Auth
# =============================================================================
def make_basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    # 優先：user/pass → 生成、無ければ JMA_AUTH_BASIC
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())
    return must_env("JMA_AUTH_BASIC").strip()


# =============================================================================
# Slack (critical only)
# =============================================================================
def slack_enabled() -> bool:
    return bool(env_str("SLACK_BOT_TOKEN")) and bool(env_str("SLACK_CHANNEL_ID"))


def slack_notify(text: str) -> None:
    # 401/403 や “全滅” など、重要な時だけ呼ぶ想定
    if not slack_enabled():
        return
    try:
        send_slack_text(channel=env_str("SLACK_CHANNEL_ID"), message=text)
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


# =============================================================================
# HTTP
# =============================================================================
def headers_for(referer: str) -> dict:
    h = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    # 公開天気図では Authorization を付けない（デフォルトOFF）
    use_auth = os.getenv("TGV_USE_AUTH", "0").strip() == "1"
    print(f"[DEBUG] TGV_USE_AUTH={'1' if use_auth else '0'}")
    print(f"[DEBUG] headers auth={'on' if 'Authorization' in h else 'off'} referer={referer}")
    if use_auth:
        h["Authorization"] = get_auth_basic()

    return h


# =============================================================================
# PNG -> JPG
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
# URL rules
# =============================================================================
def fmt_rjtd(init_dt_utc: datetime, minute: int) -> str:
    # RJTD: MMDDHHMM (UTC)
    dt = init_dt_utc.astimezone(timezone.utc).replace(minute=minute, second=0, microsecond=0)
    return dt.strftime("%m%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int, minute: int) -> datetime:
    # 探索起点も minute を揃える（MSM=03, LFM=06 など）
    dt = dt_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h, minute=minute)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(view_base: str, ft_hours: int, digits: int) -> str:
    """
    FT は VIEWコード末尾で表現（RJTDはinit固定）
    - GSM: 末尾3桁 FT（例: 3001000 -> 3001003）
    - MSM/LFM: 末尾2桁 FT（例: 500000 -> 500001）
    """
    return f"{view_base[:-digits]}{ft_hours:0{digits}d}"


# =============================================================================
# Model configs
# =============================================================================
@dataclass
class Item:
    label: str
    base: str
    layer: str
    view_base: str
    view_digits: int
    jpg_prefix: str


@dataclass
class ModelCfg:
    referer: str
    init_step_hours: int
    rjtd_minute: int
    init_probe_item: Item
    ft_list: List[int]
    slack_chunk: int
    items: List[Item]


def ft_list_gsm() -> List[int]:
    return list(range(3, 31, 3))  # 3,6,...,30


def ft_list_msm() -> List[int]:
    return list(range(1, 16)) + [18, 21, 24, 27, 30]  # 1..15 + 18..30(3h)


def ft_list_lfm() -> List[int]:
    return list(range(1, 19))  # 1..18


def load_model_groups() -> Dict[str, ModelCfg]:
    slack_chunk = env_int("SLACK_CHUNK", 10)

    GSM_WIDE = "https://www.jma.go.jp/bosai/tgv/data/GSMWide"
    MSM_WIDE = "https://www.jma.go.jp/bosai/tgv/data/MSMWide"
    MSM_NAR  = "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow"
    LFM_NAR  = "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow"

    gsm_items = [
        Item("300hPa",   GSM_WIDE, "300",  "3001000", 3, "GSM_300"),
        Item("300hPa-2", GSM_WIDE, "3002", "3101000", 3, "GSM_3002"),
    ]

    msm_items = [
        Item("500hPa",   MSM_WIDE, "500",  "500000", 2, "MSM_500"),
        Item("500hPa-2", MSM_WIDE, "5002", "510000", 2, "MSM_5002"),
        Item("700hPa",   MSM_WIDE, "700",  "700000", 2, "MSM_700"),
        Item("8502",     MSM_WIDE, "8502", "860000", 2, "MSM_8502"),   # 860001 がFT=1
        Item("050",      MSM_NAR,  "050",  "050200", 2, "MSM_050"),    # 050201 がFT=1
    ]

    lfm_items = [
        Item("850hPa",   LFM_NAR, "850",  "850200", 2, "LFM_850"),
        Item("925hPa",   LFM_NAR, "925",  "920200", 2, "LFM_925"),
        Item("975hPa",   LFM_NAR, "975",  "970200", 2, "LFM_975"),
        Item("sfc",      LFM_NAR, "sfc",  "000200", 2, "LFM_sfc"),
        Item("sfc-2",    LFM_NAR, "sfc2", "010200", 2, "LFM_sfc2"),
    ]

    return {
        "GSM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            init_step_hours=1,
            rjtd_minute=0,  # GSM: ..HH00
            init_probe_item=gsm_items[0],
            ft_list=ft_list_gsm(),
            slack_chunk=slack_chunk,
            items=gsm_items,
        ),
        "MSM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=1,
            rjtd_minute=3,  # MSM: ..HH03
            init_probe_item=msm_items[0],  # Wide側で探索
            ft_list=ft_list_msm(),
            slack_chunk=slack_chunk,
            items=msm_items,
        ),
        "LFM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=1,
            rjtd_minute=6,  # LFM: ..HH06
            init_probe_item=lfm_items[0],
            ft_list=ft_list_lfm(),
            slack_chunk=slack_chunk,
            items=lfm_items,
        ),
    }


# =============================================================================
# INIT auto-detect
# =============================================================================
def probe_init(url: str, referer: str) -> Tuple[int, str, bytes]:
    r = requests.get(url, headers=headers_for(referer), timeout=25)
    ctype = (r.headers.get("Content-Type") or "").lower()
    head = r.content[:200]
    return r.status_code, ctype, head


def find_working_init_dt(model_name: str, cfg: ModelCfg, *, max_back_hours: int = 72) -> datetime:
    """
    init探索を「今→1hずつ戻る」から
    「候補hourを回しつつ back_day を戻す」へ変更。
    これで “72h探しても見つからない” を潰しやすい。
    """
    now = datetime.now(timezone.utc)

    # モデルごとに「出現しやすいUTC時刻」を候補化（必要なら後で調整）
    if model_name == "GSM":
        hour_candidates = [0, 6, 12, 18]
    else:
        hour_candidates = list(range(0, 24))

    it0 = cfg.init_probe_item
    first_ft = cfg.ft_list[0]  # GSM=3, MSM/LFM=1
    view0 = view_for_ft(it0.view_base, first_ft, it0.view_digits)

    # 最大back_hoursを「日数」に変換して探索
    max_back_days = max(1, (max_back_hours // 24) + 1)

    for back_day in range(0, max_back_days + 1):
        day = (now - timedelta(days=back_day)).date()

        for hh in hour_candidates:
            init_dt = datetime(day.year, day.month, day.day, hh, cfg.rjtd_minute, tzinfo=timezone.utc)
            rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)
            url = build_png_url(it0.base, it0.layer, view0, rjtd)

            st, ctype, head = probe_init(url, cfg.referer)

            if st in (401, 403):
                raise RuntimeError(f"{model_name} auth error HTTP{st} url={url}")

            if st == 200:
                if ("text/html" in ctype) or head.lower().startswith(b"<!doctype html") or head.lower().startswith(b"<html"):
                    raise RuntimeError(f"{model_name} got HTML with HTTP200 (auth?) url={url}")
                print(f"[OK] {model_name} init found: {init_dt.isoformat()} RJTD_{rjtd} url={url}")
                return init_dt

    raise RuntimeError(f"{model_name}: init not found within back={max_back_hours}h")


# =============================================================================
# Fetch per item
# =============================================================================
def fetch_png(url: str, referer: str) -> Tuple[int, bytes, str]:
    r = requests.get(url, headers=headers_for(referer), timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def fetch_item_images(model_name: str, cfg: ModelCfg, init_dt: datetime, item: Item) -> Tuple[List[Attachment], bool]:
    jpg_quality = env_int("JPG_QUALITY", 85)
    rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)

    atts: List[Attachment] = []
    auth_failed = False

    for ft in cfg.ft_list:
        view_code = view_for_ft(item.view_base, ft, item.view_digits)
        url = build_png_url(item.base, item.layer, view_code, rjtd)

        status, content, ctype = fetch_png(url, cfg.referer)

        if status == 200:
            if ("text/html" in ctype) or content[:20].lower().startswith(b"<!doctype html") or content[:10].lower().startswith(b"<html"):
                auth_failed = True
                print(f"[NG] {model_name} {item.label} ft={ft}: got HTML with HTTP200 (auth?) url={url}")
                break

            jpg = png_bytes_to_jpg_bytes(content, quality=jpg_quality)
            fname = f"{item.jpg_prefix}_ft{ft:03d}.jpg"
            atts.append((fname, jpg, "image/jpeg"))
            print(f"[OK] {model_name} {item.label} ft={ft} url={url}")
            continue

        if status in (401, 403):
            auth_failed = True
            print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} auth url={url}")
            break

        if status == 404:
            continue

    return atts, auth_failed


# =============================================================================
# Delivery: Email / Slack (per item)
# =============================================================================
def send_item_mail(model_name: str, item: Item, cfg: ModelCfg, init_dt: datetime, atts: List[Attachment]) -> None:
    prefix = env_str("MAIL_SUBJECT_PREFIX", "JMA")
    subject = f"{prefix} ADV TGV {model_name} {item.label} RJTD={fmt_rjtd(init_dt, cfg.rjtd_minute)}"

    body = "\n".join([
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）",
        f"model: {model_name}",
        f"chart: {item.label}",
        f"RJTD : {fmt_rjtd(init_dt, cfg.rjtd_minute)} (UTC)",
        f"files: {len(atts)}",
        "",
        "※ 個人利用・非公開",
        "※ GitHub Actions 実行",
    ])

    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=atts,
        is_html=False,
        slack_mode="off",
    )
    print(f"[OK] mail sent: {model_name} {item.label} files={len(atts)}")


def send_item_slack(model_name: str, item: Item, cfg: ModelCfg, init_dt: datetime, atts: List[Attachment], chunk_size: int) -> None:
    channel = env_str("SLACK_CHANNEL_ID")
    if not channel:
        raise RuntimeError("SLACK_CHANNEL_ID is missing")

    rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)
    header = f"🗺️ ADV TGV {model_name} / {item.label}  RJTD={rjtd}  files={len(atts)}"

    pairs = [(fn, blob) for (fn, blob, _mime) in atts]
    for i in range(0, len(pairs), chunk_size):
        chunk = pairs[i:i + chunk_size]
        comment = header if i == 0 else f"🗺️ ADV TGV {model_name} / {item.label}（続き {i//chunk_size + 1}）"
        upload_bytes_slack(channel=channel, files=chunk, initial_comment=comment)

    print(f"[OK] slack sent: {model_name} {item.label} posts={(len(pairs)+chunk_size-1)//chunk_size}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")

    mode = env_str("DELIVERY_MODE", "both").lower()
    search_hours = env_int("INIT_SEARCH_HOURS", 72)

    groups = load_model_groups()

    for model_name in ("GSM", "MSM", "LFM"):
        cfg = groups[model_name]
        print(f"\n--- Fetch model: {model_name} items={len(cfg.items)} ---")

        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=search_hours)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)
            continue

        model_total = 0
        model_auth_failed = False

        for item in cfg.items:
            atts, auth_failed = fetch_item_images(model_name, cfg, init_dt, item)

            if auth_failed:
                model_auth_failed = True
                slack_notify(f"❌ ADV TGV {model_name} {item.label}: auth error (401/403 or HTTP200-HTML)")
                break

            if not atts:
                print(f"[WARN] {model_name} {item.label}: no images")
                continue

            model_total += len(atts)

            if mode in ("email", "both"):
                try:
                    send_item_mail(model_name, item, cfg, init_dt, atts)
                except Exception as e:
                    slack_notify(f"❌ ADV TGV {model_name} {item.label}: MAIL FAILED\n{type(e).__name__}: {e}")

            if mode in ("slack", "both"):
                try:
                    send_item_slack(model_name, item, cfg, init_dt, atts, chunk_size=cfg.slack_chunk)
                except Exception as e:
                    print(f"[WARN] Slack image send failed: {model_name} {item.label}: {e}")

        if (not model_auth_failed) and (model_total == 0):
            slack_notify(
                f"❌ ADV TGV {model_name}: no images fetched (model total=0)\nRJTD={fmt_rjtd(init_dt, cfg.rjtd_minute)}"
            )

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
