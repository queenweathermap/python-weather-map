# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster PDF → JPG → R2 → Notion DB（wx 天気図 DB）
# - カバー画像：代表1枚（必須）
# - 本文：全文画像をそのまま並べる（toggle不要・代表画像の重複なし）
# - Slack / Mail 完全撤去
#
# 要件:
# - Weathercaster も RJTD を入れる（ddHHMM / UTC基準）
# - prefix の整理ルールを ADV と揃える
#   => {R2_PREFIX}/{YYYYMMDD}/RJTD_{ddHHMM}
#
# 追加（エマグラム）:
# - 外部GIFを取得し、同じ Notion ページ本文へ追加（coverはPDF代表を維持）
#
# 追加（秋田アメダス）:
# - Weathercaster 会員ページ（fuken.html）から実況を取得
# - Notion本文に「秋田（指定観測所）」抜粋を code block で追記
# - CSV（秋田抽出）をR2へ置き、Notion本文に file ブロックで添付
#
# DELIVERY_MODE=notion 前提
# =============================================================================

from __future__ import annotations

import io
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Optional, Dict, Any

import requests
from bs4 import BeautifulSoup
from pdf2image import convert_from_bytes

from r2_utils import put_bytes, make_url

from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    set_page_cover,
    append_images,
    append_heading,
    append_code_block,
    append_files,
)

# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

PDF_FILES = [
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXJP854.pdf", "FXXN519.pdf", "FZCX50.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf", "FEFE19.pdf",
]

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

# ---- 秋田アメダス（Weathercaster会員）----
# 県別ページ（秋田が入っていればOK）
AMEDAS_ENABLE = os.environ.get("AMEDAS_ENABLE", "1").lower() in ("1", "true", "yes", "on")
AMEDAS_FUKEN_URL = os.environ.get(
    "AMEDAS_FUKEN_URL",
    "https://www.weathercaster.jp/web/member_only/weather-data/amedas/fuken.html"
).strip()

# 抜粋したい観測所（カンマ区切り）
# 例: "秋田,大館,横手,能代"
AMEDAS_STATIONS = os.environ.get("AMEDAS_STATIONS", "秋田").strip()

# CSVのファイル名（R2に置く）
AMEDAS_CSV_NAME = os.environ.get("AMEDAS_CSV_NAME", "amedas_akita.csv").strip()

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


def fetch_html_content(url: str, *, auth_required: bool = True) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    returns: (html_text, last_modified_header, http_status)
    """
    try:
        headers = {"User-Agent": "weathercaster-jma-bot/1.0"}
        if auth_required:
            r = requests.get(url, auth=(USER, PASS), headers=headers, timeout=60)
        else:
            r = requests.get(url, headers=headers, timeout=60)

        lm = r.headers.get("Last-Modified")
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text, lm, r.status_code

        print(f"[NG] html HTTP {r.status_code}: {url}")
        return None, lm, r.status_code
    except Exception as e:
        print(f"[ERR] html: {e} ({url})")
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


# ------------------------------------------------------------------
# AMEDAS parsing
# ------------------------------------------------------------------

def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u3000", " ")).strip()


def _parse_table_like_rows(soup: BeautifulSoup) -> List[List[str]]:
    """
    できるだけ汎用に「いちばんそれっぽい表」を拾う。
    - <table> を複数持つページでも、最も列が揃っていて行数が多いものを選ぶ。
    """
    best: List[List[str]] = []
    best_score = -1

    tables = soup.find_all("table")
    for t in tables:
        rows = []
        for tr in t.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            row = [_normalize_ws(c.get_text(" ", strip=True)) for c in cells]
            # 空行は捨てる
            if any(x for x in row):
                rows.append(row)

        if len(rows) < 2:
            continue

        # スコア：列数の中央値 × 行数（雑に「表らしさ」を評価）
        col_lens = [len(r) for r in rows]
        median_cols = sorted(col_lens)[len(col_lens) // 2]
        score = median_cols * len(rows)

        if score > best_score:
            best_score = score
            best = rows

    return best


def _infer_header_and_body(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """
    rows からヘッダ行っぽいものを推定して (header, body) を返す。
    - 先頭行に th が含まれるとは限らないので「先頭行をヘッダ」扱いを基本にする。
    """
    if not rows:
        return [], []
    header = rows[0]
    body = rows[1:]
    return header, body


def _filter_rows_by_station_names(header: List[str], body: List[List[str]], station_names: List[str]) -> List[List[str]]:
    """
    station_names に一致する行だけ抜粋（どの列に観測所名があるかは不明なので、行全体で部分一致）
    """
    wanted = [s for s in (station_names or []) if s]
    if not wanted:
        return []

    picked = []
    for r in body:
        joined = " ".join(r)
        if any(name in joined for name in wanted):
            picked.append(r)
    return picked


def _rows_to_aligned_text(header: List[str], rows: List[List[str]], max_rows: int = 30) -> str:
    """
    等幅表示用に整形したテキストを作る（Notion code block用）
    """
    if not header:
        return ""

    # 行を header 長に揃える
    cols = len(header)
    norm_rows = []
    for r in rows[:max_rows]:
        rr = (r + [""] * cols)[:cols]
        norm_rows.append(rr)

    # 幅
    widths = [len(h) for h in header]
    for r in norm_rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(v))

    def fmt_row(r: List[str]) -> str:
        return " | ".join((v or "").ljust(widths[i]) for i, v in enumerate(r))

    sep = "-+-".join("-" * w for w in widths)
    out = [fmt_row(header), sep]
    out += [fmt_row(r) for r in norm_rows]
    return "\n".join(out)


def _rows_to_csv_bytes(header: List[str], rows: List[List[str]]) -> bytes:
    """
    UTF-8 CSV（Excelでも読めるよう BOM 付き）
    """
    import csv

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if header:
        w.writerow(header)

    cols = len(header) if header else None
    for r in rows:
        if cols:
            rr = (r + [""] * cols)[:cols]
        else:
            rr = r
        w.writerow(rr)

    text = buf.getvalue()
    # BOM付きUTF-8
    return ("\ufeff" + text).encode("utf-8")


def fetch_akita_amedas() -> Tuple[Optional[str], Optional[bytes], Optional[str], Optional[datetime], Optional[str]]:
    """
    returns:
      excerpt_text: Notion本文用（code block）
      csv_bytes:    CSV添付用（秋田抽出）
      last_mod:     Last-Modified header
      lm_dt_utc:    parsed utc dt (if available)
      err:          エラー文言（成功時はNone）
    """
    if not AMEDAS_ENABLE:
        return None, None, None, None, None

    html, last_mod, st = fetch_html_content(AMEDAS_FUKEN_URL, auth_required=True)
    lm_dt_utc = _httpdate_to_utc_dt(last_mod) if last_mod else None

    if not html:
        return None, None, last_mod, lm_dt_utc, f"AMEDAS: download failed (HTTP={st})"

    soup = BeautifulSoup(html, "html.parser")
    rows = _parse_table_like_rows(soup)
    if not rows:
        return None, None, last_mod, lm_dt_utc, "AMEDAS: table not found"

    header, body = _infer_header_and_body(rows)
    if not header or not body:
        return None, None, last_mod, lm_dt_utc, "AMEDAS: table empty"

    station_names = [_normalize_ws(x) for x in AMEDAS_STATIONS.split(",") if _normalize_ws(x)]
    picked = _filter_rows_by_station_names(header, body, station_names)

    # 「秋田」だけにしたい：観測所指定が1つも引っかからない場合は、
    # 代替として “秋田” を含む行を拾う（県名や観測所名に入っていることが多い）
    if not picked:
        fallback = []
        for r in body:
            joined = " ".join(r)
            if "秋田" in joined:
                fallback.append(r)
        picked = fallback

    if not picked:
        # 最後の保険：先頭数行だけでも返して「構造が変わった」ことを検知できるようにする
        picked = body[:10]

    excerpt_title = " / ".join(station_names) if station_names else "秋田（抽出）"
    excerpt_text = f"Weathercaster AMeDAS（{excerpt_title}）\nURL: {AMEDAS_FUKEN_URL}\n\n"
    excerpt_text += _rows_to_aligned_text(header, picked, max_rows=30)

    csv_bytes = _rows_to_csv_bytes(header, picked)

    return excerpt_text, csv_bytes, last_mod, lm_dt_utc, None


# ------------------------------------------------------------------

def build_outputs() -> Tuple[List[Attachment], List[str], Optional[datetime], Optional[str], Optional[bytes]]:
    """
    returns:
      - images: 変換済み JPG + 追加画像（エマグラム）
      - errors: 失敗一覧
      - issued_dt_utc_guess: Last-Modified の最小値（推定）を UTC で返す（取れなければ None）
      - amedas_excerpt: Notion本文用テキスト（code block）
      - amedas_csv: CSV bytes（秋田抽出）
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []
    lm_dts: List[datetime] = []

    # --- PDFs ---
    for name in PDF_FILES:
        pdf, last_mod, st = fetch_pdf_content(name)
        if last_mod:
            dt = _httpdate_to_utc_dt(last_mod)
            if dt:
                lm_dts.append(dt)

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
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(blob)

        images.extend(atts)

    # --- Emagram GIF ---
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob, last_mod, st, ct = fetch_image_content(EMAGRAM_URL)

        if last_mod:
            dt = _httpdate_to_utc_dt(last_mod)
            if dt:
                lm_dts.append(dt)

        if blob:
            mimetype = ct if ct else "image/gif"
            fname = EMAGRAM_FILENAME or "ema_aki_00.gif"
            # cover rep_url を変えないため、末尾へ
            images.append((fname, blob, mimetype))
            try:
                with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                    f.write(blob)
            except Exception:
                pass
        else:
            errors.append(f"EMAGRAM: download failed (HTTP={st})")

    # --- AMeDAS（秋田） ---
    amedas_excerpt: Optional[str] = None
    amedas_csv: Optional[bytes] = None
    if AMEDAS_ENABLE:
        excerpt, csv_bytes, last_mod, lm_dt_utc, err = fetch_akita_amedas()
        if lm_dt_utc:
            lm_dts.append(lm_dt_utc)
        if err:
            errors.append(err)
        else:
            amedas_excerpt = excerpt
            amedas_csv = csv_bytes

    issued_dt_utc_guess = min(lm_dts) if lm_dts else None
    return images, errors, issued_dt_utc_guess, amedas_excerpt, amedas_csv


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


def upload_bytes_to_r2(run_prefix: str, filename: str, blob: bytes, content_type: str) -> Optional[str]:
    """
    1ファイルをR2へアップロードしてURLを返す
    """
    if not R2_ENABLE:
        return None
    if not filename or not blob:
        return None
    key = f"{run_prefix}/{filename}"
    put_bytes(key, blob, content_type=content_type)
    return make_url(key)


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

    # properties型（古い/別実装に備える）
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
    all_image_urls: List[str],
    errors: List[str],
    issued_guess_utc: Optional[datetime],
    amedas_excerpt: Optional[str],
    amedas_csv_url: Optional[str],
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

    # cover は代表のみ（本文に代表を重複させない）
    if rep_url:
        set_page_cover(page_id, rep_url)

    # 本文：画像一式（PDF由来＋エマグラム）
    if all_image_urls:
        append_images(page_id, all_image_urls, chunk=30)

    # 本文：秋田アメダス抜粋（code block）
    if amedas_excerpt:
        append_heading(page_id, "アメダス（秋田 抜粋）", level=2)
        append_code_block(page_id, amedas_excerpt, language="plain text")

    # 本文：CSV添付（秋田抽出）
    if amedas_csv_url:
        append_heading(page_id, "CSV 添付", level=3)
        append_files(page_id, [{"url": amedas_csv_url, "name": AMEDAS_CSV_NAME}])

    return page_id


# ------------------------------------------------------------------

def main() -> None:
    try:
        images, errors, issued_guess_utc, amedas_excerpt, amedas_csv = build_outputs()

        # 発行基準：Last-Modified の最小値があればそれ、なければ現在UTC
        base_utc_src = issued_guess_utc or _now_utc()
        issue_base_utc = _floor_to_6h(base_utc_src)

        rjtd = issue_base_utc.strftime("%d%H%M")       # ddHHMM
        day = issue_base_utc.strftime("%Y%m%d")        # YYYYMMDD
        run_prefix = f"{R2_PREFIX}/{day}/RJTD_{rjtd}"  # ADV と同型

        all_image_urls: List[str] = []
        rep_url: Optional[str] = None

        # 画像をR2へ
        if images:
            all_image_urls, rep_url = upload_to_r2(run_prefix, images)

        # CSVをR2へ（秋田抽出）
        amedas_csv_url: Optional[str] = None
        if amedas_csv:
            amedas_csv_url = upload_bytes_to_r2(
                run_prefix=run_prefix,
                filename=AMEDAS_CSV_NAME,
                blob=amedas_csv,
                content_type="text/csv"
            )

        # Notionへ
        if all_image_urls or amedas_excerpt or amedas_csv_url:
            notion_write_db(
                issue_base_utc=issue_base_utc,
                rjtd=rjtd,
                run_prefix=run_prefix,
                rep_url=rep_url,
                all_image_urls=all_image_urls,
                errors=errors,
                issued_guess_utc=issued_guess_utc,
                amedas_excerpt=amedas_excerpt,
                amedas_csv_url=amedas_csv_url,
            )

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
