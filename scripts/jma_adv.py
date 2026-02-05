# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_adv.py
#
# ADV TGV: 取得 → JPG化(3up) → R2 → Notion(DB)
# - Notion / R2 が主（配信完了の合図として Slack に静かに通知）
#
# ✅ 構成（希望どおり）
# - GSM / MSM / LFM は「見出し（タイトル）」で並べる（トグルではない）
# - 各モデル配下に、アイテムごとのトグルを作り、その中に画像を入れる
#
# ✅ ガイダンス（安定運用）
# - HTML表は取得しない（HTTP401/構造変化対策）
# - Notion本文に「リンクカード（bookmark）」で3URLを追加
#
# ✅ Slack通知（配信完了の合図）
# - module/utils/slack_utils.py の notify_weather_delivery を使用
# - @here しない
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import os
import io
import base64
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional, Sequence

import requests
from PIL import Image

from r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    create_db_row,
    set_page_cover,
    append_heading,
    append_toggle,
    append_images,
    append_bookmark,
)
from module.utils.slack_utils import notify_weather_delivery
from module.adv_tgv.models import load_model_groups, ModelCfg, Item

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


def env_bool(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


# =============================================================================
# Auth (TGV用)
# =============================================================================
def make_basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic_header() -> str:
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth_header(user.strip(), pw.strip())
    return must_env("JMA_AUTH_BASIC").strip()


def use_auth_enabled() -> bool:
    return os.getenv("TGV_USE_AUTH", "1").strip() == "1"


def get_requests_auth_tuple() -> Optional[Tuple[str, str]]:
    if not use_auth_enabled():
        return None
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return (user.strip(), pw.strip())
    return None


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
    if use_auth_enabled() and (get_requests_auth_tuple() is None):
        h["Authorization"] = get_auth_basic_header()
    return h


def http_get(url: str, *, referer: str, timeout: int) -> requests.Response:
    auth = get_requests_auth_tuple()
    return requests.get(url, headers=headers_for(referer), auth=auth, timeout=timeout)


# =============================================================================
# Image helpers
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


def make_white_jpg(width: int, height: int, *, quality: int = 85) -> bytes:
    im = Image.new("RGB", (width, height), (255, 255, 255))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def concat_jpgs_horiz(jpg_list: Sequence[bytes], *, quality: int = 85) -> bytes:
    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in jpg_list]
    try:
        h = max(im.height for im in ims)
        w = sum(im.width for im in ims)
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        x = 0
        for im in ims:
            canvas.paste(im, (x, 0))
            x += im.width
        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()
    finally:
        for im in ims:
            try:
                im.close()
            except Exception:
                pass


def maybe_triple_join_attachments(atts: List[Attachment], *, quality: int) -> List[Attachment]:
    """
    3枚を横3upで結合（余りは白でパディング）
    """
    if not env_bool("JOIN_TRIPLE", "1"):
        return atts
    if not atts:
        return atts

    joined: List[Attachment] = []
    try:
        with Image.open(io.BytesIO(atts[0][1])) as im0:
            base_w, base_h = im0.size
    except Exception:
        return atts

    i = 0
    while i < len(atts):
        group = atts[i:i + 3]

        if len(group) == 3:
            (fn1, b1, _), (_, b2, _), (_, b3, _) = group
            merged = concat_jpgs_horiz([b1, b2, b3], quality=quality)
            out_name = fn1.replace(".jpg", "") + "_3up.jpg"
            joined.append((out_name, merged, "image/jpeg"))
            i += 3
            continue

        if len(group) == 2:
            (fn1, b1, _), (_, b2, _) = group
            white = make_white_jpg(base_w, base_h, quality=quality)
            merged = concat_jpgs_horiz([b1, b2, white], quality=quality)
            out_name = fn1.replace(".jpg", "") + "_3up_pad.jpg"
            joined.append((out_name, merged, "image/jpeg"))
            i += 2
            continue

        (fn1, b1, _) = group[0]
        white1 = make_white_jpg(base_w, base_h, quality=quality)
        white2 = make_white_jpg(base_w, base_h, quality=quality)
        merged = concat_jpgs_horiz([b1, white1, white2], quality=quality)
        out_name = fn1.replace(".jpg", "") + "_3up_pad.jpg"
        joined.append((out_name, merged, "image/jpeg"))
        i += 1

    return joined


# =============================================================================
# URL rules (TGV)
# =============================================================================
def fmt_rjtd(init_dt_utc: datetime, minute: int) -> str:
    dt = init_dt_utc.astimezone(timezone.utc).replace(minute=minute, second=0, microsecond=0)
    return dt.strftime("%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int, minute: int) -> datetime:
    dt = dt_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h, minute=minute)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(view_base: str, ft_hours: int, digits: int) -> str:
    return f"{view_base[:-digits]}{ft_hours:0{digits}d}"


# =============================================================================
# INIT auto-detect / fetch
# =============================================================================
def r2_enabled() -> bool:
    return env_bool("R2_ENABLE", "1")


def fetch_item_images(model_name: str, cfg: ModelCfg, init_dt: datetime, item: Item) -> Tuple[List[Attachment], bool]:
    """
    returns: (attachments, auth_failed)
    """
    quality = env_int("JPG_QUALITY", 85)
    timeout = env_int("HTTP_TIMEOUT", 60)

    base = item.base
    layer = item.layer
    view_base = item.view_base
    digits = item.view_digits
    minute = cfg.rjtd_minute

    atts: List[Attachment] = []
    auth_failed = False

    # FT list（Itemではなく ModelCfg の ft_list を使う）
    for ft in cfg.ft_list:
        view_code = view_for_ft(view_base, ft, digits)
        rjtd = fmt_rjtd(init_dt, minute)
        url = build_png_url(base, layer, view_code, rjtd)

        try:
            r = http_get(url, referer=cfg.referer, timeout=timeout)
            if r.status_code in (401, 403):
                auth_failed = True
                break
            if r.status_code != 200:
                continue

            jpg = png_bytes_to_jpg_bytes(r.content, quality=quality)

            # ★変更点：FTをファイル名に埋め込む（Notion/R2上での整列を強化）
            # 例）xxx_FT003_VIEW....jpg  → 文字列ソートでもFT順が崩れにくい
            fn = f"{item.jpg_prefix}_FT{ft:03d}_VIEW{view_code}_RJTD_{rjtd}.jpg"

            atts.append((fn, jpg, "image/jpeg"))
        except Exception:
            continue

    atts = maybe_triple_join_attachments(atts, quality=quality)
    return atts, auth_failed


def upload_item_images_to_r2(
    *,
    run_prefix: str,
    model_name: str,
    item_label: str,
    atts: List[Attachment],
) -> List[str]:
    if not r2_enabled():
        return []
    urls: List[str] = []
    for (fn, blob, mime) in atts:
        key = f"{run_prefix}/{model_name}/{item_label}/{fn}"
        put_bytes(key, blob, content_type=mime)
        urls.append(make_url(key))
    return urls


def find_working_init_dt(model_name: str, cfg: ModelCfg, max_back_hours: int) -> datetime:
    """
    ざっくり：6時間刻みで過去へ遡り、どれか1枚取れた時点を採用する
    ※ models.py の設計通り、init_probe_item + cfg.ft_list でプローブする
    """
    timeout = env_int("HTTP_TIMEOUT", 30)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    step_hours = 6  # 「探し方」は6時間刻みでOK（運用安定）
    minute = cfg.rjtd_minute

    probe = cfg.init_probe_item
    if not cfg.ft_list:
        raise RuntimeError(f"{model_name}: cfg.ft_list is empty")

    ft0 = cfg.ft_list[0]

    for back in range(0, max_back_hours + 1, step_hours):
        init_dt = now - timedelta(hours=back)
        init_dt = floor_to_step(init_dt, step_hours=step_hours, minute=minute)

        view_code = view_for_ft(probe.view_base, ft0, probe.view_digits)
        rjtd = fmt_rjtd(init_dt, minute)
        url = build_png_url(probe.base, probe.layer, view_code, rjtd)

        r = http_get(url, referer=cfg.referer, timeout=timeout)
        if r.status_code == 200:
            return init_dt

        if r.status_code in (401, 403):
            raise RuntimeError(f"auth failed HTTP={r.status_code}")

    raise RuntimeError("INIT not found")


# =============================================================================
# Guidance links (bookmark only)
# =============================================================================
GUIDE_ENABLE = env_bool("GUIDE_ENABLE", "1")

GUIDE_LINKS: List[Tuple[str, str]] = [
    ("ガイダンス（降水）", "https://www.jma.go.jp/bosai/advisor/guid_table.html"),
    ("ガイダンス（風）", "https://www.jma.go.jp/bosai/advisor/guid_table_wind.html"),
    ("ガイダンス（寒気）", "https://www.jma.go.jp/bosai/advisor/cold_table.html"),
]


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")

    errors: List[str] = []
    total_images = 0

    search_hours = env_int("INIT_SEARCH_HOURS", 72)
    r2_prefix = env_str("R2_PREFIX", "adv-tgv").strip().strip("/")

    print(f"[DEBUG] TGV_USE_AUTH={os.getenv('TGV_USE_AUTH','')}")
    print(f"[DEBUG] JOIN_TRIPLE={os.getenv('JOIN_TRIPLE','')}")
    print(f"[DEBUG] INIT_SEARCH_HOURS={search_hours}")
    print(f"[DEBUG] R2_ENABLE={os.getenv('R2_ENABLE','')} NOTION_ENABLE={os.getenv('NOTION_ENABLE','')}")
    print(f"[DEBUG] R2_PREFIX={r2_prefix}")
    print(f"[DEBUG] GUIDE_ENABLE={GUIDE_ENABLE}")

    groups = load_model_groups()

    # --- ページの基準（タイトル/プロパティ用）は GSM init を採用 ---
    init_dt_for_title = find_working_init_dt("GSM", groups["GSM"], max_back_hours=search_hours)
    rjtd_for_title = fmt_rjtd(init_dt_for_title, groups["GSM"].rjtd_minute)

    jst = timezone(timedelta(hours=9))
    init_jst_iso = init_dt_for_title.astimezone(jst).isoformat()

    day = init_dt_for_title.strftime("%Y%m%d")
    run_prefix = f"{r2_prefix}/{day}/RJTD_{rjtd_for_title}"

    title = f"ADV TGV / {init_dt_for_title.astimezone(jst).strftime('%Y%m%d %H:%M')} JST"
    page_id = create_db_row(
        title=title,
        category="ADV TGV",
        init_jst_iso=init_jst_iso,
        memo="",
        rjtd=rjtd_for_title,
        prefix=run_prefix,
        r2_url="",
        autogen=True,
    )
    print(f"[OK] Notion DB row created: {page_id}")

    if GUIDE_ENABLE:
        append_heading(page_id, "ガイダンス（リンク）", level=2)
        for caption, url in GUIDE_LINKS:
            append_bookmark(page_id, url, caption=caption)

    first_cover_url: Optional[str] = None

    # 1) GSM / MSM / LFM
    for model_name in ("GSM", "MSM", "LFM"):
        cfg: ModelCfg = groups[model_name]
        print(f"\n--- Fetch model: {model_name} items={len(cfg.items)} ---")

        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=search_hours)
        except Exception as e:
            msg = f"{model_name}: INIT/auth failed ({type(e).__name__})"
            print(f"[NG] {msg}: {e}")
            errors.append(msg)
            continue

        append_heading(page_id, model_name, level=2)
        model_parent: str = page_id

        for item in cfg.items:
            atts, auth_failed = fetch_item_images(model_name, cfg, init_dt, item)

            if auth_failed:
                msg = f"{model_name}: auth error while fetching {item.label}"
                print(f"[NG] {msg}")
                errors.append(msg)
                break

            if not atts:
                print(f"[WARN] {model_name} {item.label}: no images")
                continue

            urls = upload_item_images_to_r2(
                run_prefix=run_prefix,
                model_name=model_name,
                item_label=item.label,
                atts=atts,
            )
            if not urls:
                continue

            total_images += len(urls)

            if (first_cover_url is None) and urls:
                first_cover_url = urls[0]
                set_page_cover(page_id, first_cover_url)

            item_title = f"{item.label}  ({len(urls)} images)"
            item_toggle_id = append_toggle(model_parent, item_title)

            if item_toggle_id:
                append_images(item_toggle_id, urls, chunk=30)
            else:
                append_images(model_parent, urls, chunk=30)

            print(f"[OK] R2+Notion: {model_name} {item.label} urls={len(urls)}")

    # ---- Slack notify（Notion配信完了の合図）----
    notify_weather_delivery(
        category="ADV TGV",
        page_id=page_id,
        errors=errors,
        attach_count=total_images,
    )

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
