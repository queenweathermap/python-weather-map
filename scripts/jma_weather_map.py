# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weather_map.py
#
# JMA Weather Map:
#   JMA PDF / PNG → JPG → R2 → Notion DB → Discord
#
# 配信内容:
#   - エマグラム（GIFをJPG化）
#   - 短期予報解説資料
#   - 週間予報解説資料
#   - 週間系PNG資料（JPG化）
#   - 地上天気図PNG 3枚（実況 / 24時間予想 / 48時間予想）
#   - 数値予報天気図PDF（00UTC / 12UTC）
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Tuple, Optional

import requests
from pdf2image import convert_from_bytes
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    append_images,
    append_heading,
    append_bookmark,
)
from module.utils.discord_utils import (
    post_discord_item_image_urls,
    post_discord_complete,
)


DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/jma_weather_map"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "jma").strip().strip("/")

JMA_UTC_OVERRIDE = os.environ.get("JMA_UTC_OVERRIDE", "").strip()

WEATHER_MAP_LIST_URL = "https://www.jma.go.jp/bosai/weather_map/data/list.json"
WEATHER_MAP_PNG_BASE_URL = "https://www.jma.go.jp/bosai/weather_map/data/png"

Attachment = Tuple[str, bytes, str]


# =============================================================================
# Discord設定
# =============================================================================
def env_bool(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


def discord_jma_webhook_url() -> str:
    return (
        os.getenv("DISCORD_JMA_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEATHERCASTER_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    )


def discord_jma_enabled() -> bool:
    return env_bool("DISCORD_ENABLE", "0") and bool(discord_jma_webhook_url())


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# エマグラム
# =============================================================================
EMAGRAM_ENABLE = os.environ.get("EMAGRAM_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EMAGRAM_URL = os.environ.get("EMAGRAM_URL", "https://bk-pro.jp/images/ema/ema_aki_00.gif").strip()
EMAGRAM_FILENAME = os.environ.get("EMAGRAM_FILENAME", "ema_aki_00.gif").strip()


# =============================================================================
# リンクのみ
# =============================================================================
AMEDAS_LINK = os.environ.get(
    "AMEDAS_LINK",
    "https://www.jma.go.jp/bosai/map.html#5/39.012/135/&elem=temp&contents=amedas",
).strip()

GUIDANCE_LINKS = [
    ("気象庁 天気図", "https://www.jma.go.jp/bosai/weather_map/"),
    ("気象庁 数値予報天気図", "https://www.jma.go.jp/bosai/numericmap/"),
    ("気象庁 分布予報", "https://www.jma.go.jp/bosai/forecast/"),
]


# =============================================================================
# 日時処理
# =============================================================================
def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(jst_tz())


def _httpdate_to_utc_dt(http_date: str) -> Optional[datetime]:
    try:
        dt = parsedate_to_datetime(http_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def select_jma_utc_run() -> str:
    """
    GitHub Actions想定:
      05:30 JST → 12UTC
      11:30 JST → 00UTC
      17:30 JST → 00UTC
      23:30 JST → 12UTC
    """
    if JMA_UTC_OVERRIDE in ("00", "12"):
        return JMA_UTC_OVERRIDE

    h = now_jst().hour
    return "00" if 10 <= h < 20 else "12"


def issue_base_utc_from_run(run_utc: str) -> datetime:
    n = now_jst()

    if run_utc == "00":
        base_jst = n.replace(hour=9, minute=0, second=0, microsecond=0)
        return base_jst.astimezone(timezone.utc)

    base_jst = n.replace(hour=21, minute=0, second=0, microsecond=0)

    if n.hour < 10:
        base_jst = base_jst - timedelta(days=1)

    return base_jst.astimezone(timezone.utc)


# =============================================================================
# 地上天気図 list.json
# =============================================================================
def build_surface_weather_map_targets() -> List[Tuple[str, str, str, bool]]:
    """
    地上天気図3枚をJMA list.jsonから取得する。

    - 実況天気図
    - 24時間予想図
    - 48時間予想図
    """
    try:
        headers = {"User-Agent": "jma-weather-map-bot/1.0"}
        r = requests.get(WEATHER_MAP_LIST_URL, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        near = data.get("near", {})

        targets: List[Tuple[str, str, str, bool]] = []

        items = [
            ("surface_now", near.get("now") or []),
            ("surface_fsas24", near.get("ft24") or []),
            ("surface_fsas48", near.get("ft48") or []),
        ]

        for base_name, files in items:
            if not files:
                print(f"[WARN] surface weather map missing: {base_name}")
                continue

            filename = files[-1]
            targets.append(
                (
                    base_name,
                    f"{WEATHER_MAP_PNG_BASE_URL}/{filename}",
                    "png",
                    False,
                )
            )

        return targets

    except Exception as e:
        print(f"[WARN] surface weather map list fetch failed: {e}")
        return []


# =============================================================================
# ダウンロード対象
# =============================================================================
def build_jma_targets(run_utc: str) -> List[Tuple[str, str, str, bool]]:
    """
    並び順 = 配信順（超重要）

    構成：
      ① エマグラム（別処理）
      ② 実況
      ③ 地上予想
      ④ 数値予報（高層 → 地上）
      ⑤ 週間
      ⑥ 解説
    """

    targets: List[Tuple[str, str, str, bool]] = []

    # =========================================================
    # ② 実況（まず現在）
    # =========================================================
    targets += build_surface_weather_map_targets()[:1]  # surface_now

    # =========================================================
    # ③ 地上予想（未来）
    # =========================================================
    surface_targets = build_surface_weather_map_targets()
    targets += surface_targets[1:]  # 24h / 48h

    # =========================================================
    # ④ 数値予報（上空 → 地上）
    # =========================================================

    # --- 高層 ---
    targets += [
        (
            f"aupa20_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/aupa20_{run_utc}.pdf",
            "pdf",
            False,
        ),
        (
            f"axjp130_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/axjp130_{run_utc}.pdf",
            "pdf",
            False,
        ),
        (
            f"axjp140_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/axjp140_{run_utc}.pdf",
            "pdf",
            False,
        ),
    ]

    # --- 中層（渦度・トラフ） ---
    targets += [
        (
            f"fxfe5782_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxfe5782_{run_utc}.pdf",
            "pdf",
            False,
        ),
        (
            f"fxfe5784_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxfe5784_{run_utc}.pdf",
            "pdf",
            False,
        ),
    ]

    # --- 下層（温度・湿り） ---
    targets += [
        (
            f"fxjp854_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxjp854_{run_utc}.pdf",
            "pdf",
            False,
        ),
    ]

    # --- 最終（地上・降水） ---
    targets += [
        (
            f"fxfe502_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxfe502_{run_utc}.pdf",
            "pdf",
            False,
        ),
        (
            f"fxfe504_{run_utc}",
            f"https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxfe504_{run_utc}.pdf",
            "pdf",
            False,
        ),
    ]

    # =========================================================
    # ⑤ 週間（スケール拡張）
    # =========================================================
    targets += [
        (
            "fefe19",
            "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fefe19.png",
            "png",
            False,
        ),
        (
            "fzcx50",
            "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fzcx50.png",
            "png",
            False,
        ),
        (
            "fxxn519",
            "https://www.jma.go.jp/bosai/numericmap/data/nwpmap/fxxn519.png",
            "png",
            False,
        ),
    ]

    # =========================================================
    # ⑥ 解説（最後に言語化）
    # =========================================================
    targets += [
        (
            "kaisetsu_tanki",
            "https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_tanki_latest.pdf",
            "pdf",
            True,
        ),
        (
            "kaisetsu_shukan",
            "https://www.data.jma.go.jp/yoho/data/jishin/kaisetsu_shukan_latest.pdf",
            "pdf",
            True,
        ),
    ]

    return targets


# =============================================================================
# 取得
# =============================================================================
def fetch_binary(name: str, url: str) -> Tuple[Optional[bytes], Optional[str], Optional[int], Optional[str]]:
    try:
        headers = {"User-Agent": "jma-weather-map-bot/1.0"}
        r = requests.get(url, headers=headers, timeout=60)

        lm = r.headers.get("Last-Modified")
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        if r.status_code == 200:
            return r.content, lm, r.status_code, ct

        print(f"[NG] {name} HTTP {r.status_code}: {url}")
        return None, lm, r.status_code, ct

    except Exception as e:
        print(f"[ERR] {name}: {e}")
        return None, None, None, None


def fetch_image_content(url: str) -> Tuple[Optional[bytes], Optional[str], Optional[int], Optional[str]]:
    try:
        headers = {"User-Agent": "jma-weather-map-bot/1.0"}
        r = requests.get(url, headers=headers, timeout=30)

        lm = r.headers.get("Last-Modified")
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        if r.status_code == 200:
            return r.content, lm, r.status_code, ct

        print(f"[NG] image HTTP {r.status_code}: {url}")
        return None, lm, r.status_code, ct

    except Exception as e:
        print(f"[ERR] image: {e} ({url})")
        return None, None, None, None


# =============================================================================
# 画像変換
# =============================================================================
def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
) -> List[Attachment]:
    images = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)

    if not images:
        return []

    out: List[Attachment] = []

    if force_all:
        for idx, im in enumerate(images, start=1):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            out.append((f"{base_filename}_p{idx:02d}.jpg", buf.getvalue(), "image/jpeg"))
        return out

    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    out.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))

    return out


def png_bytes_to_jpg(
    png_bytes: bytes,
    base_filename: str,
) -> Attachment:
    with Image.open(io.BytesIO(png_bytes)) as im:
        im = im.convert("RGB")

        out = io.BytesIO()
        im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)

        return (f"{base_filename}.jpg", out.getvalue(), "image/jpeg")


def gif_to_jpg_bytes(gif_bytes: bytes, quality: int = 85) -> bytes:
    with Image.open(io.BytesIO(gif_bytes)) as im:
        im.seek(0)
        im = im.convert("RGB")

        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


# =============================================================================
# 出力構築
# =============================================================================
def build_outputs(run_utc: str) -> Tuple[List[Attachment], List[str], Optional[datetime]]:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []
    lm_dts_all: List[datetime] = []

    for base_name, url, kind, force_all in build_jma_targets(run_utc):
        blob, last_mod, st, ct = fetch_binary(base_name, url)

        if last_mod:
            dt = _httpdate_to_utc_dt(last_mod)
            if dt:
                lm_dts_all.append(dt)

        if not blob:
            errors.append(f"{base_name}: download failed (HTTP={st})")
            continue

        try:
            if kind == "png":
                atts = [png_bytes_to_jpg(blob, base_name)]
            else:
                atts = pdf_bytes_to_jpgs(blob, base_name, force_all=force_all)

            if not atts:
                errors.append(f"{base_name}: conversion failed")
                continue

            for fname, data, _ in atts:
                try:
                    with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                        f.write(data)
                except Exception:
                    pass

            images.extend(atts)

        except Exception as e:
            errors.append(f"{base_name}: conversion failed ({e})")
            continue

    # エマグラム取得
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob, last_mod, st, ct = fetch_image_content(EMAGRAM_URL)

        if blob:
            try:
                jpg_blob = gif_to_jpg_bytes(blob, quality=JPEG_QUALITY)
                jpg_name = EMAGRAM_FILENAME.replace(".gif", ".jpg")

                images.insert(0, (jpg_name, jpg_blob, "image/jpeg"))

                try:
                    with open(os.path.join(OUTPUT_DIR, jpg_name), "wb") as f:
                        f.write(jpg_blob)
                except Exception:
                    pass

            except Exception as e:
                print(f"[WARN] emagram convert failed: {e}")
        else:
            errors.append(f"EMAGRAM: download failed (HTTP={st})")

    issued_dt_utc_guess: Optional[datetime] = max(lm_dts_all) if lm_dts_all else None

    return images, errors, issued_dt_utc_guess


# =============================================================================
# R2
# =============================================================================
def upload_to_r2(
    run_prefix: str,
    atts: List[Attachment],
) -> Tuple[List[str], Optional[str]]:
    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep_url: Optional[str] = None
    first_url: Optional[str] = None
    first_jpeg_url: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)

        url = make_url(key)
        urls.append(url)

        if first_url is None:
            first_url = url

        if first_jpeg_url is None and mime == "image/jpeg":
            first_jpeg_url = url

        if rep_url is None and fname.lower().endswith("_cover.jpg"):
            rep_url = url

    if rep_url is None:
        rep_url = first_jpeg_url or first_url

    return urls, rep_url


# =============================================================================
# Notion
# =============================================================================
def notion_write_db(
    issue_base_utc: datetime,
    rjtd: str,
    run_prefix: str,
    rep_url: Optional[str],
    all_urls: List[str],
    errors: List[str],
) -> Optional[str]:
    if not notion_enabled():
        return None

    issue_base_jst = issue_base_utc.astimezone(jst_tz())
    day = issue_base_utc.strftime("%Y%m%d")

    title = f"JMA / {day} {issue_base_jst.strftime('%H:%M')} JST"

    memo_lines: List[str] = []
    if errors:
        memo_lines.append("ERROR:")
        memo_lines += [f"- {e}" for e in errors]

    memo = "\n".join(memo_lines)

    page_id = create_db_row(
        title=title,
        category="JMA",
        init_jst_iso=issue_base_jst.isoformat(),
        memo=memo,
        rjtd=rjtd,
        prefix=run_prefix,
        r2_url=rep_url or "",
        autogen=True,
        icon_emoji="🗺️",
    )

    if not page_id:
        return None

    time.sleep(1.0)

    try:
        if GUIDANCE_LINKS:
            append_heading(page_id, "関連リンク", level=2)
            for cap, url in GUIDANCE_LINKS:
                append_bookmark(page_id, url, caption=cap)
    except Exception as e:
        print(f"[WARN] append guidance links failed: {e}")

    try:
        if AMEDAS_LINK:
            append_heading(page_id, "アメダス", level=2)
            append_bookmark(page_id, AMEDAS_LINK, caption="気象庁 アメダス")
    except Exception as e:
        print(f"[WARN] append amedas link failed: {e}")

    try:
        if all_urls:
            append_images(page_id, all_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] append_images failed: {e}")

    return page_id


# =============================================================================
# Discord
# =============================================================================
def notify_discord_jma_images(
    *,
    all_urls: List[str],
    rjtd: str,
    issue_base_utc: datetime,
) -> None:
    if not discord_jma_enabled():
        return

    issue_base_jst = issue_base_utc.astimezone(jst_tz())
    init_jst = issue_base_jst.strftime("%Y-%m-%d %H:%M JST")

    post_discord_item_image_urls(
        webhook_url=discord_jma_webhook_url(),
        title="JMA 天気図",
        image_urls=all_urls,
        notion_url="",
        rjtd=rjtd,
        init_jst=init_jst,
    )


def notify_discord_jma_complete(
    *,
    page_id: Optional[str],
    errors: List[str],
    attach_count: int,
) -> None:
    if not discord_jma_enabled():
        return

    post_discord_complete(
        webhook_url=discord_jma_webhook_url(),
        category="JMA",
        notion_url="",
        attach_count=attach_count,
        errors=errors,
    )


# =============================================================================
# main
# =============================================================================
def main() -> None:
    page_id: Optional[str] = None
    all_urls: List[str] = []
    errors: List[str] = []

    try:
        print("=== Start JMA Weather Map ===")

        run_utc = select_jma_utc_run()
        print(f"[INFO] selected JMA run: {run_utc}UTC")

        images, errors, issued_guess_utc = build_outputs(run_utc)

        issue_base_utc = issue_base_utc_from_run(run_utc)

        rjtd = issue_base_utc.strftime("%d%H%M")
        day = issue_base_utc.strftime("%Y%m%d")
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"

        rep_url: Optional[str] = None

        if images:
            all_urls, rep_url = upload_to_r2(run_prefix, images)

        if all_urls or AMEDAS_LINK or GUIDANCE_LINKS:
            page_id = notion_write_db(
                issue_base_utc=issue_base_utc,
                rjtd=rjtd,
                run_prefix=run_prefix,
                rep_url=rep_url,
                all_urls=all_urls,
                errors=errors,
            )

        if page_id:
            print(f"[OK] Notion DB row created: {page_id}")
            print(f"[OK] Notion URL: {notion_page_url(page_id)}")
        else:
            print("[WARN] Notion page was not created")

        try:
            if all_urls:
                notify_discord_jma_images(
                    all_urls=all_urls,
                    rjtd=rjtd,
                    issue_base_utc=issue_base_utc,
                )

                if discord_jma_enabled():
                    print(f"[OK] Discord images sent: {len(all_urls)}")

            notify_discord_jma_complete(
                page_id=page_id,
                errors=errors,
                attach_count=len(all_urls),
            )

            if discord_jma_enabled():
                print("[OK] Discord complete sent")

        except Exception as e:
            print(f"[WARN] Discord send failed: {e}")

        if errors:
            print("[WARN] completed with errors:")
            for e in errors:
                print(f"  - {e}")

        print("=== Done JMA Weather Map ===")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
