# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster PDF → JPG → R2 → Notion DB（wx 天気図 DB）
# - カバー画像：代表1枚（必須）
# - 本文：全文画像をそのまま並べる（toggle不要・代表画像の重複なし）
# - Slack / Mail 完全撤去
#
# 追加要件（今回）:
# - Weathercaster も RJTD を入れる（ddHHMM / UTC基準）
# - prefix の整理ルールを ADV と揃える
#   => {R2_PREFIX}/{YYYYMMDD}/RJTD_{ddHHMM}
#
# DELIVERY_MODE=notion 前提
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
)

# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

PDF_FILES = [
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
     "FXJP854.pdf","FXXN519.pdf", "FZCX50.pdf",
     "TKAISETU.pdf", "SKAISETU.pdf", "FEFE19.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER", "").strip()
PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
# ADV と揃えるため、R2_PREFIX を尊重（workflow で "weathercaster" を入れている想定）
R2_PREFIX = os.environ.get("R2_PREFIX", "weathercaster").strip().strip("/")

# --- Notion property names ---
PROP_TITLE = os.environ.get("NOTION_PROP_TITLE", "名前")
PROP_CATEGORY = os.environ.get("NOTION_PROP_CATEGORY", "区分")
PROP_MODEL = os.environ.get("NOTION_PROP_MODEL", "").strip()  # 互換用（任意）
PROP_INITJST = os.environ.get("NOTION_PROP_INIT_JST", "発行基準時刻")
PROP_MEMO = os.environ.get("NOTION_PROP_MEMO", "メモ")

PROP_AUTOGEN = os.environ.get("NOTION_PROP_AUTOGEN", "自動生成")
PROP_RJTD = os.environ.get("NOTION_PROP_RJTD", "RJTD")
PROP_PREFIX = os.environ.get("NOTION_PROP_PREFIX", "prefix")
PROP_R2URL = os.environ.get("NOTION_PROP_R2URL", "R2 URL")  # 任意。不要なら非表示運用でOK

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


def _floor_to_6h(dt_utc: datetime) -> datetime:
    """UTC 時刻を 6時間単位（00/06/12/18Z）に切り捨て。"""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_utc = dt_utc.astimezone(timezone.utc)
    h = (dt_utc.hour // 6) * 6
    return dt_utc.replace(hour=h, minute=0, second=0, microsecond=0)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
      - images: 変換済み JPG
      - errors: 失敗一覧
      - issued_dt_utc_guess: Last-Modified の最小値（推定）を UTC で返す（取れなければ None）
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []
    lm_dts: List[datetime] = []

    for name in PDF_FILES:
        pdf, last_mod, st = fetch_pdf_content(name)
        if last_mod:
            dt = _httpdate_to_utc_dt(last_mod)
            if dt:
                lm_dts.append(dt)

        if not pdf:
            errors.append(f"{name}: download failed (HTTP={st})")
            continue

        # 一旦ファイル名用の base は「当日」ではなく、後で決まる issue_day を使って付け替える
        # ここでは仮名で作って、アップロード時に prefix で整理する
        base = name.replace(".pdf", "")

        force_all = name in ("SKAISETU.pdf", "TKAISETU.pdf")
        atts = pdf_bytes_to_jpgs(pdf, base, force_all=force_all)

        if not atts:
            errors.append(f"{name}: conversion failed")
            continue

        for fname, blob, _ in atts:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(blob)

        images.extend(atts)

    issued_dt_utc_guess = min(lm_dts) if lm_dts else None
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
    - (A) 引数型: create_db_row(title=..., category=..., init_jst_iso=..., memo=..., rjtd=..., prefix=..., r2_url=..., autogen=..., icon_emoji=...)
    - (B) properties型: create_db_row(database_id=..., properties=..., rjtd=..., prefix=..., icon_emoji=...)
    """
    # A: 引数型（今のあなたの jma_weathercaster.py が使っている形）
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

    # B: properties型（古い/別実装に備える）
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
            # 互換列がある場合だけ入れる
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
    issued_guess_utc: Optional[datetime],
) -> Optional[str]:
    if not notion_enabled():
        return None

    issue_base_jst = issue_base_utc.astimezone(jst_tz())
    day = issue_base_utc.strftime("%Y%m%d")

    # タイトル（必要なら好みで微調整OK）
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

    # cover は代表のみ（本文に代表を重複させない）
    if rep_url:
        set_page_cover(page_id, rep_url)

    # 本文：全文画像をそのまま並べる（toggle不要）
    append_images(page_id, all_urls, chunk=30)

    return page_id


# ------------------------------------------------------------------

def main() -> None:
    try:
        images, errors, issued_guess_utc = build_outputs()

        # 発行基準：Last-Modified の最小値があればそれ、なければ現在UTC
        base_utc_src = issued_guess_utc or _now_utc()
        issue_base_utc = _floor_to_6h(base_utc_src)

        rjtd = issue_base_utc.strftime("%d%H%M")      # ddHHMM
        day = issue_base_utc.strftime("%Y%m%d")       # YYYYMMDD
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}" # ADV と同型

        all_urls: List[str] = []
        rep_url: Optional[str] = None

        if images:
            all_urls, rep_url = upload_to_r2(run_prefix, images)

        if all_urls:
            notion_write_db(
                issue_base_utc=issue_base_utc,
                rjtd=rjtd,
                run_prefix=run_prefix,
                rep_url=rep_url,
                all_urls=all_urls,
                errors=errors,
                issued_guess_utc=issued_guess_utc,
            )

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
