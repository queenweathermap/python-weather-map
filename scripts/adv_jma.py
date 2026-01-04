# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を自動取得し、
# “天気図ごと（itemごと）” に Slack 投稿（/メール）する。
#
# ✅ 最終仕様
# - 取得元：JMA tgv の PNG
# - Slack/メール送信：JPG（PNGより軽量化）
# - 送信単位：天気図ごと（itemごと）に分割
# - INIT（RJTD）は「存在する初期時刻」を自動探索
# - FT は VIEWコード末尾で表現（RJTDはinit固定）  ← 重要
# - Slack通知：404は出さない
#   * 401/403（認証系） or モデル全滅（1枚も取れない）だけ通知
#
# ✅ 環境変数
# - JMA_ADV_USER / JMA_ADV_PASS  (推奨)   または JMA_AUTH_BASIC ("Basic xxxx")
# - SLACK_BOT_TOKEN / SLACK_CHANNEL_ID    (Slack投稿したい場合)
# - DELIVERY_MODE = slack | email | both  (default: slack)
# - SLACK_CHUNK = 10                      (default: 10)  1投稿の枚数
#
# - GSM_MAX_FT (default=27) / GSM_FT_STEP (default=3)
# - MSM_MAX_FT (default=0)  / MSM_FT_STEP (default=1)
# - LFM_MAX_FT (default=0)  / LFM_FT_STEP (default=1)
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
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }


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
def fmt_rjtd(init_dt_utc: datetime) -> str:
    # RJTD: MMDDHHMM (UTC), 分は00固定
    dt = init_dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%m%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int) -> datetime:
    dt = dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(view_base: str, ft_hours: int) -> str:
    """
    FT は VIEWコード末尾で表現する（RJTDはinit固定）

    - GSM: 7桁（例 3102000） → 末尾3桁をFT(000/003/006...)に
    - MSM/LFM: 6桁（例 500200） → 末尾2桁をFT(00/01/02...)に
    """
    digits = 3 if len(view_base) >= 7 else 2
    return f"{view_base[:-digits]}{ft_hours:0{digits}d}"


# =============================================================================
# Model configs
# =============================================================================
@dataclass
class Item:
    label: str
    layer: str
    view_bases: List[str]   # base view（ft=0相当を置く）
    jpg_prefix: str


@dataclass
class ModelCfg:
    base: str
    referer: str
    init_step_hours: int
    ft_list: List[int]
    items: List[Item]


def build_ft_list(max_ft: int, step: int) -> List[int]:
    if max_ft < 0:
        return [0]
    return list(range(0, max_ft + 1, step))


def load_model_groups() -> Dict[str, ModelCfg]:
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
            ft_list=build_ft_list(gsm_max, gsm_step),
            items=[
                Item(label="300hPa",   layer="300",  view_bases=["3002000"], jpg_prefix="GSM_300"),
                Item(label="300hPa-2", layer="3002", view_bases=["3102000"], jpg_prefix="GSM_3002"),
            ],
        ),
        "MSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/MSMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=1,
            ft_list=build_ft_list(msm_max, msm_step),
            items=[
                Item(label="500hPa",   layer="500",  view_bases=["500200"], jpg_prefix="MSM_500"),
                Item(label="500hPa-2", layer="5002", view_bases=["510200"], jpg_prefix="MSM_5002"),
                Item(label="700hPa",   layer="700",  view_bases=["700200"], jpg_prefix="MSM_700"),
            ],
        ),
        "LFM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/LFMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=1,
            ft_list=build_ft_list(lfm_max, lfm_step),
            items=[
                Item(label="850hPa",   layer="850",  view_bases=["850200"], jpg_prefix="LFM_850"),
                Item(label="850hPa-2", layer="8502", view_bases=["860200"], jpg_prefix="LFM_8502"),
                Item(label="925hPa",   layer="925",  view_bases=["920200"], jpg_prefix="LFM_925"),
                Item(label="975hPa",   layer="975",  view_bases=["970200"], jpg_prefix="LFM_975"),
                Item(label="sfc",      layer="sfc",  view_bases=["000200"], jpg_prefix="LFM_sfc"),
                Item(label="sfc-2",    layer="sfc2", view_bases=["010200"], jpg_prefix="LFM_sfc2"),
            ],
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
    重要：
    - 404は“普通に起きる”ので例外にしない（HTMLでもOK）
    - 401/403は認証エラー
    - 200なのにHTMLは認証ページ/ブロック疑い
    """
    step = cfg.init_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step)

    it0 = cfg.items[0]
    base_view = it0.view_bases[0]
    view0 = view_for_ft(base_view, 0)

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
        rjtd = fmt_rjtd(init_dt)
        url = build_png_url(cfg.base, it0.layer, view0, rjtd)

        try:
            st, ctype, head = probe_init(url, cfg.referer)

            if st == 200:
                # 200でもHTMLならおかしい（認証ページ等）
                if ("text/html" in ctype) or head.lower().startswith(b"<!doctype html") or head.lower().startswith(b"<html"):
                    raise RuntimeError(f"{model_name} got HTML with HTTP200 (auth?) url={url}")

                print(f"[OK] {model_name} init found: {init_dt.isoformat()} (RJTD_{rjtd}) url={url}")
                return init_dt

            if st in (401, 403):
                raise RuntimeError(f"{model_name} auth error HTTP{st} url={url}")

            # 404含む、それ以外は探索継続
            print(f"[NG] {model_name} init RJTD_{rjtd} HTTP{st} url={url}")

        except Exception as e:
            print(f"[ERR] {model_name} init probe failed: {type(e).__name__}: {e}")

    raise RuntimeError(f"{model_name}: init not found within back={max_back_hours}h")


# =============================================================================
# Fetch per item
# =============================================================================
def fetch_png(url: str, referer: str) -> Tuple[int, bytes, str]:
    r = requests.get(url, headers=headers_for(referer), timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def fetch_item_images(model_name: str, cfg: ModelCfg, init_dt: datetime, item: Item) -> Tuple[List[Attachment], bool]:
    """
    1天気図ぶん取得
    - 404はよくあるので黙ってスキップ（printは出す）
    - 401/403 or 200なのにHTML（認証ページ疑い）なら auth_failed=True
    """
    jpg_quality = env_int("JPG_QUALITY", 85)
    rjtd = fmt_rjtd(init_dt)  # ✅ RJTDはinit固定

    atts: List[Attachment] = []
    auth_failed = False

    for ft in cfg.ft_list:
        got = False

        for base_view in item.view_bases:
            view_code = view_for_ft(base_view, ft)
            url = build_png_url(cfg.base, item.layer, view_code, rjtd)

            try:
                status, content, ctype = fetch_png(url, cfg.referer)

                if status == 200:
                    # 200でHTMLは異常（ログインHTML等）
                    if ("text/html" in ctype) or content[:20].lower().startswith(b"<!doctype html") or content[:10].lower().startswith(b"<html"):
                        auth_failed = True
                        print(f"[NG] {model_name} {item.label} ft={ft}: got HTML with HTTP200 (auth?) url={url}")
                        got = False
                        break

                    jpg = png_bytes_to_jpg_bytes(content, quality=jpg_quality)
                    fname = f"{item.jpg_prefix}_ft{ft:03d}.jpg"
                    atts.append((fname, jpg, "image/jpeg"))
                    print(f"[OK] {model_name} {item.label} ft={ft} url={url}")
                    got = True
                    break

                if status in (401, 403):
                    auth_failed = True
                    print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} auth url={url}")
                    got = False
                    break

                if status == 404:
                    print(f"[NG] {model_name} {item.label} ft={ft}: HTTP404 url={url}")
                    continue

                print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} url={url}")

            except Exception as e:
                print(f"[ERR] {model_name} {item.label} ft={ft}: {type(e).__name__}: {e} url={url}")

        if auth_failed:
            break

        if not got:
            continue

    return atts, auth_failed


# =============================================================================
# Delivery: Email / Slack (per item)
# =============================================================================
def send_item_mail(model_name: str, item: Item, init_dt: datetime, atts: List[Attachment]) -> None:
    prefix = env_str("MAIL_SUBJECT_PREFIX", "JMA")
    init_str = init_dt.strftime("%m/%d %H:00(UTC)")
    subject = f"{prefix} ADV TGV {model_name} {item.label} init={init_str}"

    body = "\n".join([
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）",
        f"model: {model_name}",
        f"chart: {item.label}",
        f"init : {init_str}",
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


def send_item_slack(model_name: str, item: Item, init_dt: datetime, atts: List[Attachment]) -> None:
    channel = env_str("SLACK_CHANNEL_ID")
    if not channel:
        raise RuntimeError("SLACK_CHANNEL_ID is missing")

    chunk_size = env_int("SLACK_CHUNK", 10)
    init_str = init_dt.strftime("%m/%d %H:00(UTC)")
    header = f"🗺️ ADV TGV {model_name} / {item.label}  init={init_str}  files={len(atts)}"

    pairs = [(fn, blob) for (fn, blob, _mime) in atts]
    for i in range(0, len(pairs), chunk_size):
        chunk = pairs[i:i + chunk_size]
        comment = header if i == 0 else f"🗺️ ADV TGV {model_name} / {item.label}（続き {i//chunk_size + 1}）"
        upload_bytes_slack(channel=channel, files=chunk, initial_comment=comment)

    print(f"[OK] slack sent: {model_name} {item.label} files={len(atts)}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")

    mode = env_str("DELIVERY_MODE", "slack").lower()
    groups = load_model_groups()

    for model_name in ("GSM", "MSM", "LFM"):
        cfg = groups[model_name]
        print(f"\n--- Fetch model: {model_name} items={len(cfg.items)} ---")

        # 1) init探索
        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=72)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)
            continue

        model_total = 0
        model_auth_failed = False

        # 2) itemごとに取得 → メール（本命）→ Slack画像（副系）
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
                    send_item_mail(model_name, item, init_dt, atts)
                except Exception as e:
                    slack_notify(
                        f"❌ ADV TGV {model_name} {item.label}: MAIL FAILED\n{type(e).__name__}: {e}"
                    )

            if mode in ("slack", "both"):
                try:
                    send_item_slack(model_name, item, init_dt, atts)
                except Exception as e:
                    print(f"[WARN] Slack image send failed: {model_name} {item.label}: {e}")

        # 3) モデル全滅だけ通知（あなたの希望）
        if (not model_auth_failed) and (model_total == 0):
            slack_notify(
                f"❌ ADV TGV {model_name}: no images fetched (model total=0)\ninit={init_dt.strftime('%m/%d %H:00(UTC)')}"
            )

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
