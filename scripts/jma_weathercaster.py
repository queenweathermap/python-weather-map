# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster:
#   PDF → JPG → R2 → Notion DB → Discord
#
# 役割分担:
#   - Notion / R2 が正本
#   - Discord は画像ビューア
#   - Slack は使わない
#
# Discord設計:
#   - Weathercaster専用チャンネルへ投稿
#   - 画像はR2 URLをembed表示
#   - 1投稿最大10画像
#   - 最後にNotion URL付き完了通知を投稿
#
# エマグラム設計:
#   - 本文にはGIFをそのまま表示
#   - Notionカバー用にGIFの1フレーム目をJPG化
#   - カバーはJPGにすることでNotion 400エラーを避ける
# =============================================================================

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import io
import os
import shutil
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Optional

import requests
from pdf2image import convert_from_bytes
from PIL import Image

from r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    set_page_cover,
    append_images,
    append_heading,
    append_bookmark,
)
from module.utils.discord_utils import (
    post_discord_item_image_urls,
    post_discord_complete,
)


# =============================================================================
# 基本設定
# =============================================================================
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"

PDF_FILES = [
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXJP854.pdf", "FXXN519.pdf", "FZCX50.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf", "FEFE19.pdf",
]

PROBE_PDFS_ENV = os.environ.get("WEATHERCASTER_ISSUE_PROBE_PDFS", "").strip()

USER = os.environ.get("WEATHERCASTER_USER", "").strip()
PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX = os.environ.get("R2_PREFIX", "weathercaster").strip().strip("/")


# =============================================================================
# Discord設定
# =============================================================================
def env_bool(name: str, default: str = "0") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


def discord_weathercaster_webhook_url() -> str:
    """
    Weathercaster専用DiscordチャンネルのWebhook URL。

    優先:
      DISCORD_WEATHERCASTER_WEBHOOK_URL

    互換:
      DISCORD_WEBHOOK_URL
    """
    return (
        os.getenv("DISCORD_WEATHERCASTER_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    )


def discord_weathercaster_enabled() -> bool:
    return env_bool("DISCORD_ENABLE", "0") and bool(discord_weathercaster_webhook_url())


def notion_page_url(page_id: str) -> str:
    """
    Notionのpage_idからブラウザURLを作る。
    """
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
    "https://www.weathercaster.jp/web/member_only/weather-data/amedas/fuken.html"
).strip()

GUIDANCE_LINKS = [
    (
        "GSMガイダンス",
        "https://www.weathercaster.jp/web/member_only/weather-data/guidance/gui_ken_hour.html",
    ),
    (
        "MSMガイダンス",
        "https://www.weathercaster.jp/web/member_only/weather-data/msm_guidance/gui_ken_hour.html",
    ),
    (
        "週間ガイダンス",
        "https://www.weathercaster.jp/web/member_only/weather-data/week_guidance/gui_all_daily.html",
    ),
    (
        "気象庁 分布予報（市町村一覧）",
        "https://www.weathercaster.jp/web/member_only/weather-data/jma_yoho/bunpu_office_2.cgi#05",
    ),
]


Attachment = Tuple[str, bytes, str]


# =============================================================================
# 日時処理
# =============================================================================
def jst_tz() -> timezone:
    return timezone(timedelta(hours=9))


def _httpdate_to_utc_dt(http_date: str) -> Optional[datetime]:
    """
    Last-ModifiedなどのHTTP-dateをUTC datetimeへ変換する。
    """
    try:
        dt = parsedate_to_datetime(http_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_probe_pdfs() -> List[str]:
    """
    発行基準時刻の推定に使うPDFを選ぶ。
    指定があればそれを使い、なければCOMP系を優先する。
    """
    if PROBE_PDFS_ENV:
        return [p.strip() for p in PROBE_PDFS_ENV.split(",") if p.strip()]

    comp = [p for p in PDF_FILES if p.startswith("COMP")]
    return comp if comp else PDF_FILES[:]


def _floor_to_6h_jst_03_09_15_21(dt_utc: datetime) -> datetime:
    """
    JSTの03/09/15/21時に丸める。
    """
    jst = jst_tz()

    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)

    dt_jst = dt_utc.astimezone(jst)

    dt_shift = dt_jst - timedelta(hours=3)
    h = (dt_shift.hour // 6) * 6
    dt_floor = dt_shift.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(hours=3)

    return dt_floor.astimezone(timezone.utc)


# =============================================================================
# 取得
# =============================================================================
def fetch_pdf_content(name: str) -> Tuple[Optional[bytes], Optional[str], Optional[int]]:
    """
    WeathercasterのPDFを取得する。
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
    外部画像を取得する。
    エマグラムGIF取得に使う。
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


# =============================================================================
# 画像変換
# =============================================================================
def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
) -> List[Attachment]:
    """
    PDFをJPGへ変換する。

    通常:
      1ページ目のみ

    TKAISETU / SKAISETU:
      複数ページを全部JPG化
    """
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


def gif_to_jpg_bytes(gif_bytes: bytes, quality: int = 85) -> bytes:
    """
    GIFの1フレーム目をJPGに変換する。

    用途:
      Notionカバー用。

    理由:
      Notionカバーに外部GIFを指定すると400エラーになることがあるため。
      本文にはGIFをそのまま表示し、カバーだけJPGにする。
    """
    with Image.open(io.BytesIO(gif_bytes)) as im:
        im.seek(0)
        im = im.convert("RGB")

        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


# =============================================================================
# 出力構築
# =============================================================================
def build_outputs() -> Tuple[List[Attachment], List[str], Optional[datetime]]:
    """
    PDF群とエマグラムを取得し、R2へアップロードするための画像配列を作る。

    戻り値:
      images:
        R2へ上げる画像一覧

      errors:
        取得・変換エラー一覧

      issued_dt_utc_guess:
        発行基準時刻の推定
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    images: List[Attachment] = []
    errors: List[str] = []

    lm_dts_pdf_all: List[datetime] = []
    lm_dts_pdf_probe: List[datetime] = []
    probe_set = set(_parse_probe_pdfs())

    # -------------------------------------------------------------------------
    # PDF取得
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # エマグラム取得
    #
    # ここが今回の重要ポイント:
    #   1. 本文用GIFを残す
    #   2. カバー用JPGも生成する
    #
    # 順番:
    #   先頭: エマグラムJPG（Notionカバー候補）
    #   次:   エマグラムGIF（本文表示用）
    # -------------------------------------------------------------------------
    if EMAGRAM_ENABLE and EMAGRAM_URL:
        blob, last_mod, st, ct = fetch_image_content(EMAGRAM_URL)

        if blob:
            gif_name = EMAGRAM_FILENAME or "ema_aki_00.gif"

            # 本文用GIF
            gif_mime = ct if ct else "image/gif"
            gif_attachment: Attachment = (gif_name, blob, gif_mime)

            # カバー用JPG
            try:
                jpg_blob = gif_to_jpg_bytes(blob, quality=JPEG_QUALITY)

                if gif_name.lower().endswith(".gif"):
                    jpg_name = gif_name[:-4] + "_cover.jpg"
                else:
                    jpg_name = gif_name + "_cover.jpg"

                jpg_attachment: Attachment = (jpg_name, jpg_blob, "image/jpeg")

                # カバー用JPGを最優先にする
                images.insert(0, gif_attachment)
                images.insert(0, jpg_attachment)

                try:
                    with open(os.path.join(OUTPUT_DIR, jpg_name), "wb") as f:
                        f.write(jpg_blob)
                    with open(os.path.join(OUTPUT_DIR, gif_name), "wb") as f:
                        f.write(blob)
                except Exception:
                    pass

            except Exception as e:
                # JPG変換に失敗した場合でも、本文用GIFは残す
                print(f"[WARN] emagram gif->jpg failed: {e}")
                images.insert(0, gif_attachment)

                try:
                    with open(os.path.join(OUTPUT_DIR, gif_name), "wb") as f:
                        f.write(blob)
                except Exception:
                    pass

        else:
            errors.append(f"EMAGRAM: download failed (HTTP={st})")

    # 発行基準時刻はPDFのLast-Modifiedから推定
    issued_dt_utc_guess: Optional[datetime] = None

    if lm_dts_pdf_probe:
        issued_dt_utc_guess = max(lm_dts_pdf_probe)
    elif lm_dts_pdf_all:
        issued_dt_utc_guess = max(lm_dts_pdf_all)

    return images, errors, issued_dt_utc_guess


# =============================================================================
# R2
# =============================================================================
def upload_to_r2(
    run_prefix: str,
    atts: List[Attachment],
) -> Tuple[List[str], Optional[str]]:
    """
    R2へアップロードする。

    戻り値:
      all_urls:
        Notion本文・Discord表示に使う全URL

      rep_url:
        Notionカバーに使う代表URL

    代表URLの選び方:
      1. *_cover.jpg を最優先
      2. なければ最初のimage/jpeg
      3. それもなければ最初のURL
    """
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
    """
    Notion DBへ1ページ作成する。

    module/utils/notion_utils.py の create_db_row() に合わせる。
    """
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

    page_id = create_db_row(
        title=title,
        category="Weathercaster",
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

    # -------------------------------------------------------------------------
    # カバー画像
    #
    # カバー用JPGを使う想定。
    # ただし、Notion側で外部URLを拒否する場合もあるため、
    # 失敗しても全体を止めない。
    # -------------------------------------------------------------------------
    # -----------------------------
    # ガイダンスリンク
    # -----------------------------
    try:
        if GUIDANCE_LINKS:
            append_heading(page_id, "ガイダンス・関連リンク", level=2)
            for cap, url in GUIDANCE_LINKS:
                append_bookmark(page_id, url, caption=cap)
    except Exception as e:
        print(f"[WARN] append guidance links failed: {e}")

    # -----------------------------
    # アメダスリンク
    # -----------------------------
    try:
        if AMEDAS_LINK:
            append_heading(page_id, "アメダス（リンク）", level=2)
            append_bookmark(page_id, AMEDAS_LINK, caption="秋田 AMeDAS（府県別）")
    except Exception as e:
        print(f"[WARN] append amedas link failed: {e}")

    # -----------------------------
    # 画像本文
    # -----------------------------
    try:
        if all_urls:
            append_images(page_id, all_urls, chunk=30)
    except Exception as e:
        print(f"[WARN] append_images failed: {e}")

    return page_id

# =============================================================================
# Discord
# =============================================================================
def notify_discord_weathercaster_images(
    *,
    all_urls: List[str],
    rjtd: str,
    issue_base_utc: datetime,
) -> None:
    """
    Weathercaster画像投稿。

    Notion URLはここでは出さない。
    最後の完了通知だけに出す。
    """
    if not discord_weathercaster_enabled():
        return

    issue_base_jst = issue_base_utc.astimezone(jst_tz())
    init_jst = issue_base_jst.strftime("%Y-%m-%d %H:%M JST")

    post_discord_item_image_urls(
        webhook_url=discord_weathercaster_webhook_url(),
        title="Weathercaster / JMA天気図",
        image_urls=all_urls,
        notion_url="",
        rjtd=rjtd,
        init_jst=init_jst,
    )


def notify_discord_weathercaster_complete(
    *,
    page_id: Optional[str],
    errors: List[str],
    attach_count: int,
) -> None:
    """
    Weathercaster完了通知。

    最後にNotion URLを表示する。
    """
    if not discord_weathercaster_enabled():
        return

    post_discord_complete(
        webhook_url=...,
        category="Weathercaster",
        notion_url="",
        attach_count=...,
        errors=...,
    )

# =============================================================================
# main
# =============================================================================
def main() -> None:
    page_id: Optional[str] = None
    all_urls: List[str] = []
    errors: List[str] = []

    try:
        print("=== Start Weathercaster JMA ===")

        images, errors, issued_guess_utc = build_outputs()

        base_utc_src = issued_guess_utc or datetime.now(timezone.utc)
        issue_base_utc = _floor_to_6h_jst_03_09_15_21(base_utc_src)

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
                notify_discord_weathercaster_images(
                    all_urls=all_urls,
                    rjtd=rjtd,
                    issue_base_utc=issue_base_utc,
                )

                if discord_weathercaster_enabled():
                    print(f"[OK] Discord images sent: {len(all_urls)}")

            notify_discord_weathercaster_complete(
                page_id=page_id,
                errors=errors,
                attach_count=len(all_urls),
            )

            if discord_weathercaster_enabled():
                print("[OK] Discord complete sent")

        except Exception as e:
            print(f"[WARN] Discord send failed: {e}")

        print("=== Done Weathercaster JMA ===")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
