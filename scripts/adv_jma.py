# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を自動取得し、
# “天気図ごと（itemごと）” にメール送信（必須）＋Slack投稿（副系）する。
#
# ✅ 仕様（あなたの現行URL規則に完全準拠）
# - FT は VIEWコード末尾で表現（RJTDは init 固定）
# - GSM: FT=3..30 (3h) 10枚 / item（Slack 1投稿・メール1通）
# - MSM: FT=1..15(1h) + 18,21,24,27,30 合計20枚 / item（Slack 2投稿・メール1通）
# - LFM: FT=1..18(1h) 18枚 / item（Slack 2投稿(10+8)・メール1通）
# - Slack通知（テキスト）は 401/403 or モデル全滅のみ（404は通知しない）
#
# ✅ 環境変数
# - JMA_ADV_USER / JMA_ADV_PASS  (推奨)   または JMA_AUTH_BASIC ("Basic xxxx")
# - DELIVERY_MODE = email | slack | both  (default: both)  ※メール必須想定だが切替可
# - SLACK_BOT_TOKEN / SLACK_CHANNEL_ID    (Slack投稿したい場合)
# - SLACK_CHUNK = 10                      (default: 10)
# - JPG_QUALITY = 85                      (default: 85)
# - INIT_SEARCH_HOURS = 72                (default: 72)
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
    layer: str
    view_base: str      # ft=0 相当の VIEWコード（末尾は 00...0）
    view_digits: int    # FT差し替え桁数（GSM=3, MSM/LFM=2）
    jpg_prefix: str


@dataclass
class ModelCfg:
    base: str
    referer: str
    init_step_hours: int
    init_probe_item: Item
    ft_list: List[int]
    slack_chunk: int
    items: List[Item]


def ft_list_gsm() -> List[int]:
    # FT=3..30 (3h): 3,6,...,30 => 10
    return list(range(3, 31, 3))


def ft_list_msm() -> List[int]:
    # FT=1..15 (1h) = 15枚 + 18,21,24,27,30 = 5枚 => 20
    return list(range(1, 16)) + [18, 21, 24, 27, 30]


def ft_list_lfm() -> List[int]:
    # FT=1..18 (1h) => 18
    return list(range(1, 19))


def load_model_groups() -> Dict[str, ModelCfg]:
    slack_chunk = env_int("SLACK_CHUNK", 10)

    gsm_items = [
        Item(label="300hPa",   layer="300",  view_base="3001000", view_digits=3, jpg_prefix="GSM_300"),
        Item(label="300hPa-2", layer="3002", view_base="3101000", view_digits=3, jpg_prefix="GSM_3002"),
    ]
    
    msm_items = [
        Item(label="500hPa",   layer="500",  view_base="500000", view_digits=3, jpg_prefix="MSM_500"),
        Item(label="500hPa-2", layer="5002", view_base="510000", view_digits=3, jpg_prefix="MSM_5002"),
        Item(label="700hPa",   layer="700",  view_base="700000", view_digits=3, jpg_prefix="MSM_700"),
    ]
    
    lfm_items = [
        Item(label="850hPa",   layer="850",  view_base="850200", view_digits=3, jpg_prefix="LFM_850"),
        Item(label="850hPa-2", layer="8502", view_base="860200", view_digits=3, jpg_prefix="LFM_8502"),
        Item(label="925hPa",   layer="925",  view_base="920200", view_digits=3, jpg_prefix="LFM_925"),
        Item(label="975hPa",   layer="975",  view_base="970200", view_digits=3, jpg_prefix="LFM_975"),
        Item(label="sfc",      layer="sfc",  view_base="000200", view_digits=3, jpg_prefix="LFM_sfc"),
        Item(label="sfc-2",    layer="sfc2", view_base="010200", view_digits=3, jpg_prefix="LFM_sfc2"),
    ]

    return {
        "GSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/GSMWide",
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            init_step_hours=1,  # 探索は1h刻みでOK（実際にある時刻にヒットさせやすい）
            init_probe_item=gsm_items[0],
            ft_list=ft_list_gsm(),
            slack_chunk=slack_chunk,  # 10
            items=gsm_items,
        ),
        "MSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/MSMWide",
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=1,
            init_probe_item=msm_items[0],
            ft_list=ft_list_msm(),
            slack_chunk=slack_chunk,  # 10（=10+10）
            items=msm_items,
        ),
        "LFM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/LFMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=1,
            init_probe_item=lfm_items[0],
            ft_list=ft_list_lfm(),
            slack_chunk=slack_chunk,  # 10（=10+8）
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
    - 404は普通に起きる（HTMLでもOK）ので例外にしない
    - 401/403は認証エラー
    - 200なのにHTMLは認証ページ/ブロック疑い
    """
    step = cfg.init_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step)

    it0 = cfg.init_probe_item
    view0 = view_for_ft(it0.view_base, 0, it0.view_digits)

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
        rjtd = fmt_rjtd(init_dt)
        url = build_png_url(cfg.base, it0.layer, view0, rjtd)

        st, ctype, head = probe_init(url, cfg.referer)

        if st == 200:
            if ("text/html" in ctype) or head.lower().startswith(b"<!doctype html") or head.lower().startswith(b"<html"):
                # 200でHTMLは異常
                raise RuntimeError(f"{model_name} got HTML with HTTP200 (auth?) url={url}")
            print(f"[OK] {model_name} init found: {init_dt.isoformat()} RJTD_{rjtd}")
            return init_dt

        if st in (401, 403):
            raise RuntimeError(f"{model_name} auth error HTTP{st} url={url}")

        # 404等は探索継続
        # print(f"[NG] {model_name} init RJTD_{rjtd} HTTP{st}")

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
    - 404はよくあるので黙ってスキップ（printはOK）
    - 401/403 or 200なのにHTML（認証ページ疑い）なら auth_failed=True
    """
    jpg_quality = env_int("JPG_QUALITY", 85)
    rjtd = fmt_rjtd(init_dt)  # ✅ RJTDはinit固定

    atts: List[Attachment] = []
    auth_failed = False

    for ft in cfg.ft_list:
        view_code = view_for_ft(item.view_base, ft, item.view_digits)
        url = build_png_url(cfg.base, item.layer, view_code, rjtd)

        status, content, ctype = fetch_png(url, cfg.referer)

        if status == 200:
            # 200でHTMLは異常（ログインHTML等）
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
            # Slackには出さない
            # print(f"[404] {model_name} {item.label} ft={ft}")
            continue

        # その他
        # print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} url={url}")

    return atts, auth_failed


# =============================================================================
# Delivery: Email / Slack (per item)
# =============================================================================
def send_item_mail(model_name: str, item: Item, init_dt: datetime, atts: List[Attachment]) -> None:
    prefix = env_str("MAIL_SUBJECT_PREFIX", "JMA")
    init_str = init_dt.strftime("%m/%d %H:00(UTC)")
    subject = f"{prefix} ADV TGV {model_name} {item.label} RJTD={fmt_rjtd(init_dt)}"

    body = "\n".join([
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）",
        f"model: {model_name}",
        f"chart: {item.label}",
        f"RJTD : {fmt_rjtd(init_dt)} (UTC)",
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


def send_item_slack(model_name: str, item: Item, init_dt: datetime, atts: List[Attachment], chunk_size: int) -> None:
    channel = env_str("SLACK_CHANNEL_ID")
    if not channel:
        raise RuntimeError("SLACK_CHANNEL_ID is missing")

    rjtd = fmt_rjtd(init_dt)
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

        # 1) init探索
        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=search_hours)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)
            continue

        model_total = 0
        model_auth_failed = False

        # 2) itemごとに取得 → メール（必須）→ Slack画像（副系）
        for item in cfg.items:
            atts, auth_failed = fetch_item_images(model_name, cfg, init_dt, item)

            if auth_failed:
                model_auth_failed = True
                slack_notify(f"❌ ADV TGV {model_name} {item.label}: auth error (401/403 or HTTP200-HTML)")
                break

            if not atts:
                # item全滅はよくあるので通知しない
                print(f"[WARN] {model_name} {item.label}: no images")
                continue

            model_total += len(atts)

            # メール（本命）
            if mode in ("email", "both"):
                try:
                    send_item_mail(model_name, item, init_dt, atts)
                except Exception as e:
                    slack_notify(f"❌ ADV TGV {model_name} {item.label}: MAIL FAILED\n{type(e).__name__}: {e}")

            # Slack（副系）
            if mode in ("slack", "both"):
                try:
                    # chunkはモデル共通で10想定（GSM=10, MSM=10+10, LFM=10+8）
                    send_item_slack(model_name, item, init_dt, atts, chunk_size=cfg.slack_chunk)
                except Exception as e:
                    print(f"[WARN] Slack image send failed: {model_name} {item.label}: {e}")

        # 3) モデル全滅だけ通知
        if (not model_auth_failed) and (model_total == 0):
            slack_notify(
                f"❌ ADV TGV {model_name}: no images fetched (model total=0)\nRJTD={fmt_rjtd(init_dt)}"
            )

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
