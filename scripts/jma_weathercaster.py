# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster PDF → JPG → R2 → Notion DB（wx 天気図 DB）
# - カバー画像：代表1枚（必須）
# - 本文：画像一式を並べる（代表画像の重複なし）
#
# 追加（エマグラム）:
# - 外部GIFを取得し、同じ Notion ページ本文へ追加（coverはPDF代表を維持）
#
# 追加（リンクカード増量）:
# - 取得はしない（HTTP401/構造変化対策）
# - Notion本文の先頭に「ブックマーク（リンクカード）」で複数URLを追加する
#
# 追加（Slack通知）:
# - Notion配信完了したら #wx-python に通知（Webhook優先）
#
# ★堅牢化（重要）
# - issued_guess（発行推定）は PDF の Last-Modified を優先（エマグラムLMには引っ張られない）
# - 遅延PDFでズレないよう「プローブPDF集合」を env で指定可能:
#     WEATHERCASTER_ISSUE_PROBE_PDFS="COMP12.pdf,COMP36.pdf,COMP72.pdf"
# - init（発行基準時刻）は JST の 03/09/15/21 に揃える
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Optional, Dict, Any

import requests
from pdf2image import convert_from_bytes

from r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    set_page_cover,
    append_images,
    append_heading,
    append_bookmark,
)
from module.utils.slack_utils import notify_weather_delivery


# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

PDF_FILES = [
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXJP854.pdf", "FXXN519.pdf", "FZCX50.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf", "FEFE19.pdf",
]

# issued_guess（発行推定）に使う “基準PDF” を限定したい場合（推奨）
# 例: WEATHERCASTER_ISSUE_PROBE_PDFS="COMP12.pdf,COMP36.pdf,COMP72.pdf"
PROBE_PDFS_ENV = os.environ.get("WEATHERCASTER_ISSUE_PROBE_PDFS", "").strip()

USER = os.environ.get("WEATHERCASTER_USER", "").strip()
PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "weathercaster").strip().strip("/")

# ---- エマグラム ----
EMAGRAM_ENABLE = os.environ.get("EMAGRAM_ENABLE", "1").lower() in ("1", "true", "yes", "on")
EMAGRAM_URL = os.environ.get("EMAGRAM_URL", "https://bk-pro.jp/images/ema/ema_aki_00.gif").strip()
EMAGRAM_FILENAME = os.environ.get("EMAGRAM_FILENAME", "ema_aki_00.gif").strip()

# ---- アメダス（リンクのみ）----
AMEDAS_LINK = os.environ.get(
    "AMEDAS_LINK",
    "https://www.weathercaster.jp/web/member_only/weather-data/amedas/fuken.html"
).strip()

# ---- ガイダンス・関連リンク（リンクのみ）----
GUIDANCE_LINKS = [
    ("GSMガイダンス",
     "https://www.weathercaster.jp/web/member_only/weather-data/guidance/gui_ken_hour.html"),
    ("MSMガイダンス",
     "https://www.weathercaster.jp/web/member_only/weather-data/msm_guidance/gui_ken_hour.html"),
    ("週間ガイダンス",
     "https://www.weathercaster.jp/web/member_only/weather-data/week_guidance/gui_all_daily.html"),
    ("気象庁 分布予報（市町村一覧）",
     "https://www.weathercaster.jp/web/member_only/weather-data/jma_yoho/bunpu_office_2.cgi#05"),
]

# --- Notion property names ---
PROP_TITLE = os.environ.get("NOTION_PROP_TITLE", "名前")
PROP_CATEGORY = os.environ.get("NOTION_PROP_CATEGORY", "区分")
PROP_MODEL = os.environ.get("NOTION_PROP_MODEL", "").strip()  # 互換用（任意）
PROP_INITJST = os.environ.get("NOTION_PROP_INIT_JST", "発行基準時刻")
PROP_MEMO = os.environ.get("NOTION_PROP_MEMO", "メモ")

PROP_AUTOGEN = os.environ.get("NOTION_PROP_AUTOGEN", "自動生成")
PROP_RJTD = os.environ.get("NOTION_PROP_RJTD", "RJTD")
PROP_PREFIX = os.environ.get("NOTION_PROP_PREFIX", "prefix")
PROP_R2URL = os.environ.get("NOTION_PROP_R2URL", "R2 URL")  # 任意

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


# ------------------------------------------------------------------

def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def _httpdate_to_utc_dt(http_date: str) -> Optional[datetime]:
    """HTTP-date を tz-aware UTC datetime に。"""
    try:
        dt = parsedate_to_datetime(http_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_probe_pdfs() -> List[str]:
    """
    発行推定に使う “基準PDF” のリスト。
    指定があればそれを使用。なければ COMP系を優先、なければ全PDF。
    """
    if PROBE_PDFS_ENV:
        parts = [p.strip() for p in PROBE_PDFS_ENV.split(",") if p.strip()]
        return parts

    comp = [p for p in PDF_FILES if p.startswith("COMP")]
    return comp if comp else PDF_FILES[:]


def _floor_to_6h_jst_03_09_15_21(dt_utc: datetime) -> datetime:
    """
    JSTで 03/09/15/21 の6時間境界に切り捨ててから UTC に戻す。
    例) 12:51JST → 09:00JST, 16:51JST → 15:00JST
    """
    jst = jst_tz()
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    dt_jst = dt_utc.astimezone(jst)

    # 3時間オフセットして 6h丸め → 3時間戻す
    dt_shift = dt_jst - timedelta(hours=3)
    h = (dt_shift.hour // 6) * 6
    dt_floor = dt_shift.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(hours=3)

    return dt_floor.astimezone(timezone.utc)


def fetch_pdf_content(name: str) -> Tuple[Optional[bytes], Optional[str], Optional[int]]:
    """
    returns: (content, last_modified_header, http_status)
    """
    url = f"{BASE_URL}/{name}"
    try:
        r = requests.get(url, auth=(USER, PASS), timeout=60)
        lm = r.headers.get("Last-Modified")
        if r.status_code == 200:
            return r.content, lm, r.status_code
        print(f"[NG] {name} HTTP {r.status_code}")
        return None, lm, r.status_code
    except Exception as e:
        print(f"[ERR] {name}: {e}")
        return None, None, None


def fetch_image_content(url: str) -> Tuple[Optional[bytes], Optional[str], Optional[int], Optional[str]]:
    """
    returns: (content, last_modified_header, http_status, content_type)
    """
    try:
        headers = {"User-Agent": "weathercaster-jma-bot/1.0"}
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


def pdf_bytes_to_jpgs(pdf_bytes: bytes, base_filename: str, force_all: bool = False) -> List[Attachment]:
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

    # 代表は1枚目のみ（ただし本文には出さず、cover にのみ使う）
    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    out.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))
    return out


def build_outputs() -> Tuple[List[Attachment], List[str], Optional[datetime]]:
    """
    returns:
      - images: 変換済み JPG + エマグラム（GIF）
      - errors: 失敗一覧
      - issued_dt_utc_guess: 発行基準時刻の推定（UTC）
        ※ PDFの更新時刻を優先し、エマグラムのLMには引っ張られない
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []

    # PDFの LM を「全部」と「プローブ対象」に分けて持つ（遅延PDF対策）
    lm_dts_pdf_all: List[datetime] = []
    lm_dts_pdf_probe: List[datetime] = []
    probe_set = set(_parse_probe_pdfs())

    # --- PDFs ---
    for name in PDF_FILES:
        pdf, last_mod, st = fetch_pdf_content(name)

        if last_mod:
            dt = _httpdate_to_utc_dt(last_mod)
            if dt:
                lm_dts_pdf_all.append(dt)
                if name in probe_set:
                    lm_dts_pdf_probe.append(dt)

        if not pdf:
            errors.append(f"{name}: download failed (HTTP={st})")
            continue

        base = name.replace(".pdf", "")
        force_all = name in ("SKAISETU.pdf", "TKAISETU.pdf")
        atts = pdf_bytes_to_jpgs(pdf, base, force_all=force_all)

        if not atts:
            errors.append(f"{name}: conversion failed")
            continue

        for fname, blob, _ in atts:
            try:
                with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                    f.write(blob)
            except Exception:
                pass

        images.extend(atts)

    # --- Emagram GIF（本文画像の先頭に配置） ---
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob, last_mod, st, ct = fetch_image_content(EMAGRAM_URL)

        # ★重要：エマグラムの Last-Modified は “基準時刻” 判定に使わない
        # （LMが古い/固定/欠落で、09:00 側に引っ張られることがある）
        if blob:
            mimetype = ct if ct else "image/gif"
            fname = EMAGRAM_FILENAME or "ema_aki_00.gif"

            images.insert(0, (fname, blob, mimetype))

            try:
                with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                    f.write(blob)
            except Exception:
                pass
        else:
            errors.append(f"EMAGRAM: download failed (HTTP={st})")

    # ★基準時刻は「プローブPDFの最新更新」を最優先（無ければ全PDFの最新）
    issued_dt_utc_guess: Optional[datetime] = None
    if lm_dts_pdf_probe:
        issued_dt_utc_guess = max(lm_dts_pdf_probe)
    elif lm_dts_pdf_all:
        issued_dt_utc_guess = max(lm_dts_pdf_all)

    return images, errors, issued_dt_utc_guess


def upload_to_r2(run_prefix: str, atts: List[Attachment]) -> Tuple[List[str], Optional[str]]:
    """
    returns: (all_urls, rep_url)
    - rep_url は最初にアップロードした画像（代表）
    """
    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep: Optional[str] = None

    for fname, blob, mime in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)
        urls.append(url)
        if not rep:
            rep = url

    return urls, rep


def _create_db_row_compat(
    title: str,
    category: str,
    init_jst_iso: str,
    memo: str,
    rjtd: str,
    prefix: str,
    autogen: bool,
) -> Optional[str]:
    """
    notion_utils.create_db_row の実装差を吸収する互換ラッパー。
    """
    try:
        return create_db_row(
            title=title,
            category=category,
            init_jst_iso=init_jst_iso,
            memo=memo,
            rjtd=rjtd,
            prefix=prefix,
            r2_url="",
            autogen=autogen,
            icon_emoji="🗺️",
        )
    except TypeError:
        pass

    try:
        db = os.environ.get("NOTION_DATABASE_ID", "").strip()
        if not db:
            return None

        props: Dict[str, Any] = {
            PROP_TITLE: {"title": [{"type": "text", "text": {"content": title}}]},
            PROP_CATEGORY: {"select": {"name": category}},
            PROP_INITJST: {"date": {"start": init_jst_iso}},
            PROP_AUTOGEN: {"checkbox": bool(autogen)},
        }
        if PROP_MODEL:
            props[PROP_MODEL] = {"select": {"name": category}}
        if memo:
            props[PROP_MEMO] = {"rich_text": [{"type": "text", "text": {"content": memo[:1900]}}]}
        if rjtd:
            props[PROP_RJTD] = {"rich_text": [{"type": "text", "text": {"content": rjtd}}]}
        if prefix:
            props[PROP_PREFIX] = {"rich_text": [{"type": "text", "text": {"content": prefix}}]}

        return create_db_row(
            database_id=db,
            properties=props,
            rjtd=rjtd,
            prefix=prefix,
            icon_emoji="🗺️",
        )
    except Exception:
        return None


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

    title = f"Weathercaster / {day} {issue_base_jst.strftime('%H:%M')} JST"

    memo_lines: List[str] = []
    if errors:
        memo_lines.append("ERROR:")
        memo_lines += [f"- {e}" for e in errors]
    memo = "\n".join(memo_lines)

    page_id = _create_db_row_compat(
        title=title,
        category="Weathercaster",
        init_jst_iso=issue_base_jst.isoformat(),
        memo=memo,
        rjtd=rjtd,
        prefix=run_prefix,
        autogen=True,
    )
    if not page_id:
        return None

    if rep_url:
        set_page_cover(page_id, rep_url)

    if GUIDANCE_LINKS:
        append_heading(page_id, "ガイダンス・関連リンク", level=2)
        for cap, url in GUIDANCE_LINKS:
            append_bookmark(page_id, url, caption=cap)

    if AMEDAS_LINK:
        append_heading(page_id, "アメダス（リンク）", level=2)
        append_bookmark(page_id, AMEDAS_LINK, caption="秋田 AMeDAS（府県別）")

    if all_urls:
        append_images(page_id, all_urls, chunk=30)

    return page_id


def main() -> None:
    page_id: Optional[str] = None
    all_urls: List[str] = []
    errors: List[str] = []

    try:
        images, errors, issued_guess_utc = build_outputs()

        base_utc_src = issued_guess_utc or datetime.now(timezone.utc)

        # “イニシャル”は JST 03/09/15/21 に揃える
        issue_base_utc = _floor_to_6h_jst_03_09_15_21(base_utc_src)

        rjtd = issue_base_utc.strftime("%d%H%M")       # ddHHMM
        day = issue_base_utc.strftime("%Y%m%d")        # YYYYMMDD
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"  # ADV と同型

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
            notify_weather_delivery(
                category="Weathercaster",
                page_id=page_id,
                errors=errors,
                attach_count=len(all_urls),
            )

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
