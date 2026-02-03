# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_adv.py
#
# ADV TGV: 取得 → JPG化(3up) → R2 → Notion(DB) → Mail/Slack
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import os
import io
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional, Sequence

import requests
from PIL import Image


from r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    create_db_row,
    set_page_cover,
    append_heading,
    append_toggle,
    append_images,
)

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
# Auth
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
# Delivery (Notion/R2 only)
# =============================================================================

def slack_enabled() -> bool:
    return False


def slack_notify(text: str) -> None:
    # Slack is fully disabled in Notion-only mode
    return


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

        if len(group) == 1:
            (fn1, b1, _) = group[0]
            white1 = make_white_jpg(base_w, base_h, quality=quality)
            white2 = make_white_jpg(base_w, base_h, quality=quality)
            merged = concat_jpgs_horiz([b1, white1, white2], quality=quality)
            out_name = fn1.replace(".jpg", "") + "_3up_pad.jpg"
            joined.append((out_name, merged, "image/jpeg"))
            i += 1
            continue

    return joined


# =============================================================================
# URL rules
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
# Model configs (externalized)
# =============================================================================
from module.adv_tgv.models import load_model_groups, Item, ModelCfg



# =============================================================================
# INIT auto-detect
# =============================================================================
def probe_init(url: str, referer: str) -> Tuple[int, str, bytes]:
    r = http_get(url, referer=referer, timeout=25)
    ctype = (r.headers.get("Content-Type") or "").lower()
    head = r.content[:200]
    return r.status_code, ctype, head


def find_working_init_dt(model_name: str, cfg: ModelCfg, *, max_back_hours: int = 72) -> datetime:
    step = cfg.init_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step, cfg.rjtd_minute)

    it0 = cfg.init_probe_item
    first_ft = cfg.ft_list[0]
    view0 = view_for_ft(it0.view_base, first_ft, it0.view_digits)

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
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
    r = http_get(url, referer=referer, timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def fetch_item_images(model_name: str, cfg: ModelCfg, init_dt: datetime, item: Item) -> Tuple[List[Attachment], bool]:
    jpg_quality = env_int("JPG_QUALITY", 85)
    rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)

    raw_atts: List[Attachment] = []
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
            raw_atts.append((fname, jpg, "image/jpeg"))
            print(f"[OK] {model_name} {item.label} ft={ft} url={url}")
            continue

        if status in (401, 403):
            auth_failed = True
            print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} auth url={url}")
            break

        if status == 404:
            continue

    atts = maybe_triple_join_attachments(raw_atts, quality=jpg_quality)
    return atts, auth_failed


# =============================================================================
# R2
# =============================================================================
def r2_enabled() -> bool:
    v = env_str("R2_ENABLE", "1").lower()
    return v in ("1", "true", "yes", "on")


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


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")

    mode = env_str("DELIVERY_MODE", "notion").lower()  # notion only
    search_hours = env_int("INIT_SEARCH_HOURS", 72)

    print(f"[DEBUG] TGV_USE_AUTH={os.getenv('TGV_USE_AUTH','')}")
    print(f"[DEBUG] JOIN_TRIPLE={os.getenv('JOIN_TRIPLE','')}")
    print(f"[DEBUG] DELIVERY_MODE={mode} (notion-only)")
    print(f"[DEBUG] INIT_SEARCH_HOURS={search_hours}")
    print(f"[DEBUG] R2_ENABLE={os.getenv('R2_ENABLE','')} NOTION_ENABLE={os.getenv('NOTION_ENABLE','')}")

    groups = load_model_groups()

    # --- DB row create (Notion) ---
    page_id = None
    run_prefix = None
    first_cover_url = ""

    try:
        init_dt_for_title = find_working_init_dt("GSM", groups["GSM"], max_back_hours=search_hours)
        rjtd_for_title = fmt_rjtd(init_dt_for_title, groups["GSM"].rjtd_minute)

        # 初期時刻（JST）を Date(時刻あり) として入れる
        jst = timezone(timedelta(hours=9))
        init_jst_iso = init_dt_for_title.astimezone(jst).isoformat()

        run_prefix = f"adv-tgv/{init_dt_for_title.strftime('%Y%m%d')}/RJTD_{rjtd_for_title}"

        title = f"ADV TGV / {init_dt_for_title.astimezone(jst).strftime('%Y-%m-%d %H:%M')} JST"
        page_id = create_db_row(
            title=title,
            category="ADV",
            init_jst_iso=init_jst_iso,
            memo="",
            rjtd=rjtd_for_title,
            prefix=run_prefix,
            r2_url="",
            autogen=True,
        )


        print(f"[OK] Notion DB row created: {page_id}")
    except Exception as e:
        import traceback
        print("[WARN] Notion DB row create skipped (full):")
        traceback.print_exc()

        # NotionのHTTPエラーなら本文を出す（400の詳細がここに入る）
        try:
            import requests
            if isinstance(e, requests.HTTPError) and e.response is not None:
                print("[WARN] Notion response status:", e.response.status_code)
                print("[WARN] Notion response body:", e.response.text[:2000])
        except Exception:
            pass

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

        if page_id:
            try:
                append_heading(page_id, f"{model_name}", level=2)
            except Exception as e:
                print(f"[WARN] notion append heading failed: {e}")

        for item in cfg.items:
            atts, auth_failed = fetch_item_images(model_name, cfg, init_dt, item)

            if auth_failed:
                model_auth_failed = True
                msg = f"❌ ADV TGV {model_name} {item.label}: auth error (401/403 or HTTP200-HTML)"
                print(msg)
                slack_notify(msg)
                break

            if not atts:
                print(f"[WARN] {model_name} {item.label}: no images")
                continue

            model_total += len(atts)

            # --- R2 -> Notion(toggle) ---
            if page_id and run_prefix and r2_enabled():
                try:
                    urls = upload_item_images_to_r2(
                        run_prefix=run_prefix,
                        model_name=model_name,
                        item_label=item.label,
                        atts=atts,
                    )

                    # 初回だけ代表画像をカバーにする（最初のURL）
                    if (not first_cover_url) and urls:
                        first_cover_url = urls[0]
                        set_page_cover(page_id, first_cover_url)

                    # toggleの中に画像展開
                    t_title = f"{model_name} / {item.label}  ({len(urls)} images)"
                    toggle_id = append_toggle(page_id, t_title)  # returns block_id

                    if toggle_id:
                        append_images(toggle_id, urls, chunk=30)
                    else:
                        # 保険：トグル作れないなら直下に貼る
                        append_images(page_id, urls, chunk=30)

                    print(f"[OK] R2+Notion(toggle): {model_name} {item.label} urls={len(urls)}")

                except Exception as e:
                    msg = f"❌ R2/Notion FAILED {model_name} {item.label}\n{type(e).__name__}: {e}"
                    print(msg)
                    slack_notify(msg)

        if (not model_auth_failed) and (model_total == 0):
            msg = (
                f"❌ ADV TGV {model_name}: no images fetched (model total=0)\n"
                f"RJTD={fmt_rjtd(init_dt, cfg.rjtd_minute)}"
            )
            print(msg)
            slack_notify(msg)

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
