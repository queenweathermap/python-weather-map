# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/guidance.py
#
# JMA Guidance:
#   HTML → スクショ → JPG → R2一時保存 → Notion取り込み → Discord
#
# 方針:
#   ・Notion = 正本
#   ・R2 = 21日保存の一時置き場
#   ・Discord = ビュー
#   ・ポータルリンクはテキスト投稿
# =============================================================================

from __future__ import annotations

import io
import os
import re
import shutil
import sys
import time
import requests

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Optional

from PIL import Image
from playwright.sync_api import sync_playwright


from module.utils.r2_utils import put_bytes, make_url
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    append_images,
    append_imported_images_from_urls,
    append_heading,
    append_bookmark,
)
from module.utils.discord_utils import (
    post_discord_item_image_urls,
    post_discord_complete,
)

# =============================================================================
# 設定
# =============================================================================

OUTPUT_DIR = "/tmp/jma_guidance"

JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "90"))
R2_ENABLE = os.environ.get("R2_ENABLE", "1") in ("1", "true", "yes")
R2_PREFIX = os.environ.get("R2_PREFIX", "guidance")

VIEWPORT_WIDTH = int(os.environ.get("GUIDANCE_VIEWPORT_WIDTH", "1200"))
VIEWPORT_HEIGHT = int(os.environ.get("GUIDANCE_VIEWPORT_HEIGHT", "900"))
WAIT_MS = int(os.environ.get("GUIDANCE_WAIT_MS", "2500"))

NOTION_IMPORT_IMAGES = os.environ.get("NOTION_IMPORT_IMAGES", "0").lower() in ("1", "true", "yes", "on")
NOTION_IMPORT_TIMEOUT_SECONDS = int(os.environ.get("NOTION_IMPORT_TIMEOUT_SECONDS", "180"))
NOTION_IMPORT_POLL_SECONDS = float(os.environ.get("NOTION_IMPORT_POLL_SECONDS", "2.0"))

Attachment = Tuple[str, bytes, str]

# =============================================================================
# WCN（気象キャスターネットワーク）会員ページ。Basic認証（WEATHERCASTER_USER/PASS）。
# 直URLは東京に戻るため、各ページで「府県選択→決定」して iframe(data_area) に
# 秋田を描画させ、その frame を丸ごと撮る（固定高さに依らず全地点を取得）。
# =============================================================================
WCN_BASE = os.environ.get(
    "WCN_BASE", "https://www.weathercaster.jp/web/member_only/weather-data")
WCN_PREF = os.environ.get("WCN_PREF", "秋田県")
WCN_PORTAL = f"{WCN_BASE}/msm_guidance/gui_ken_hour.html"

# 撮影対象。mode:
#   "select_frame" … 府県選択→決定→iframe(data_area)を撮影（パラメータ無しページ）
#   "page"         … 直URL（#05=秋田 等のハッシュ）を開いてページ全体を撮影
# days: select_frame で撮る日のオフセット一覧（0=当日, 1=明日…）。
#   1以上は「現在日付」チェックを外し、日付セレクトを当日+offset日に設定して決定する。
GUIDANCE_TARGETS = [
    {
        "name": "wcn_msm_ken_hour",
        "label": "MSM府県時別",
        "url": f"{WCN_BASE}/msm_guidance/gui_ken_hour.html",
        "mode": "select_frame",
        "days": [0, 1],   # 当日・明日の2枚
    },
    {
        "name": "wcn_bunpu_office",
        "label": "予報分布(府県別)",
        "url": f"{WCN_BASE}/jma_yoho/bunpu_office_2.cgi#05",  # #05 = 秋田県
        "mode": "page",
    },
]
# =============================================================================
# Utility
# =============================================================================

def jst_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))

def _day_label(day_offset: int) -> str:
    return {0: "当日", 1: "明日", 2: "明後日"}.get(day_offset, f"+{day_offset}日")

def png_to_jpg(png_bytes):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=JPEG_QUALITY)
    return out.getvalue()

def discord_url():
    return os.getenv("DISCORD_GUIDANCE_WEBHOOK_URL", "")


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# スクショ
# =============================================================================

def _select_pref(page):
    """府県選択＝WCN_PREF を選ぶ（決定は押さない）。最初の select に都道府県が入っている。"""
    page.locator("select").first.select_option(label=WCN_PREF)


def _click_decide(page):
    """「決定」ボタン（input[submit/button] や button、空白入り "決 定" に対応）を押す。"""
    try:
        page.get_by_role("button", name=re.compile(r"決\s*定")).first.click()
    except Exception:
        page.locator(
            "input[type=submit], input[type=button], button"
        ).filter(has_text=re.compile(r"決\s*定")).first.click()


def _set_date_offset(page, day_offset):
    """『年月日』セレクト（オプション例: 06月13日）を当日+day_offset日に設定する。
    当日＋数日先が1つの結合セレクトに入っている方式。年は表示に含まれないため
    月・日で一致を取る（年またぎは稀なので考慮しない既知の制限）。"""
    target = jst_now() + timedelta(days=day_offset)
    mm, dd = target.month, target.day

    sels = page.locator("select")
    try:
        n = sels.count()
    except Exception:
        n = 0

    for i in range(n):
        sel = sels.nth(i)
        try:
            texts = sel.locator("option").evaluate_all(
                "els => els.map(e => (e.textContent || '').trim())")
        except Exception:
            continue

        # 「◯月◯日」形式のオプションを持つ select ＝ 日付セレクト
        is_date_select = False
        match_idx = None
        for idx, tx in enumerate(texts):
            m = re.search(r"(\d+)\s*月\s*(\d+)\s*日", tx)
            if m:
                is_date_select = True
                if int(m.group(1)) == mm and int(m.group(2)) == dd:
                    match_idx = idx
                    break

        if not is_date_select:
            continue
        if match_idx is None:
            print(f"[WARN] 日付セレクトに {mm:02d}月{dd:02d}日 が無い: {texts}")
            return False
        try:
            sel.select_option(index=match_idx, timeout=3000)
            print(f"[INFO] 日付セレクト設定 offset={day_offset} → {texts[match_idx]}")
            return True
        except Exception as e:
            print(f"[WARN] 日付セレクト選択に失敗: {e}")
            return False

    print(f"[WARN] 『年月日』セレクトが見つからない offset={day_offset}")
    return False


def _select_pref_and_decide(page):
    """後方互換: 府県選択→決定（当日）。"""
    _select_pref(page)
    _click_decide(page)


def capture():
    atts = []
    errors = []

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    user = os.getenv("WEATHERCASTER_USER", "").strip()
    password = os.getenv("WEATHERCASTER_PASS", "").strip()

    if not user or not password:
        errors.append("WCN auth env is missing: WEATHERCASTER_USER / WEATHERCASTER_PASS")
        return atts, errors

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            http_credentials={"username": user, "password": password},
        )
        page = context.new_page()

        for t in GUIDANCE_TARGETS:
            name, label, url, mode = t["name"], t["label"], t["url"], t["mode"]
            # select_frame は当日/明日…を撮れる。page は当日のみ。
            days = t.get("days", [0]) if mode == "select_frame" else [0]

            for day in days:
                day_label = _day_label(day)
                shot_name = name if day == 0 else f"{name}_d{day}"
                full_label = f"{label}（{day_label}）" if mode == "select_frame" else label
                try:
                    print(f"[INFO] {full_label}")
                    page.goto(url, wait_until="networkidle", timeout=60000)

                    if mode == "select_frame":
                        # 府県＝秋田県を選び、明日以降は日付セレクトを進めてから決定
                        _select_pref(page)
                        if day > 0:
                            _set_date_offset(page, day)
                        _click_decide(page)
                        page.wait_for_load_state("networkidle", timeout=60000)
                        page.wait_for_timeout(WAIT_MS)
                        target = page.frame(name="data_area")
                        if target is None:
                            errors.append(f"{full_label}: iframe 'data_area' が見つからない")
                            continue
                    else:  # "page"：ハッシュ(#05)指定の府県分布など、ページ全体を撮る
                        try:
                            page.evaluate("window.dispatchEvent(new HashChangeEvent('hashchange'))")
                        except Exception:
                            pass
                        page.wait_for_timeout(WAIT_MS)
                        target = page

                    # 秋田が描画されたか軽く待つ（失敗しても撮影は続行）
                    try:
                        target.get_by_text(WCN_PREF[:2], exact=False).first.wait_for(timeout=10000)
                    except Exception:
                        pass

                    body_text = target.locator("body").inner_text(timeout=5000)
                    if "Authentication Failed" in body_text or "Unauthorized" in body_text:
                        errors.append(f"{full_label}: authentication failed")
                        continue

                    # iframe は body 要素、ページは full_page で全体を撮る
                    if mode == "select_frame":
                        png = target.locator("body").screenshot(type="png")
                    else:
                        png = target.screenshot(full_page=True, type="png")

                    atts.append((f"{shot_name}.png", png, "image/png"))

                except Exception as e:
                    errors.append(f"{full_label}: {e}")

        context.close()
        browser.close()

    return atts, errors

# =============================================================================
# R2
# =============================================================================

def upload(prefix, atts):
    urls = []
    rep = None

    if not R2_ENABLE:
        return urls, rep

    for fname, blob, mime in atts:
        key = f"{prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)

        urls.append(url)
        if rep is None:
            rep = url

    return urls, rep

# =============================================================================
# Notion
# =============================================================================

def write_notion(base_jst, prefix, urls, rep, errors, atts):
    if not notion_enabled():
        return None

    title = f"Guidance / {base_jst.strftime('%Y%m%d %H:%M')}"

    page_id = create_db_row(
        title=title,
        category="Guidance",
        init_jst_iso=base_jst.isoformat(),
        memo="\n".join(errors),
        rjtd="",
        prefix=prefix,
        r2_url=rep or "",
        autogen=True,
        icon_emoji="📊",
    )

    if not page_id:
        return None

    time.sleep(1)

    try:
        append_heading(page_id, "ガイダンス画像", level=2)

        if urls:
            if NOTION_IMPORT_IMAGES:
                items = []
                for idx, url in enumerate(urls):
                    if idx < len(atts):
                        fname, _blob, mime = atts[idx]
                    else:
                        fname, mime = f"guidance_{idx + 1:02d}.jpg", "image/jpeg"
                    items.append((fname, url, mime or "image/jpeg"))

                append_imported_images_from_urls(
                    page_id,
                    items,
                    chunk=10,
                    timeout_seconds=NOTION_IMPORT_TIMEOUT_SECONDS,
                    poll_seconds=NOTION_IMPORT_POLL_SECONDS,
                )
            else:
                append_images(page_id, urls)

    except Exception as e:
        print(f"[WARN] Notion image import/append failed: {e}")

        # 移行中の安全策: Notion取り込みに失敗した場合は従来の外部URL埋め込みへ戻す
        try:
            if urls:
                append_images(page_id, urls)
        except Exception as e2:
            print(f"[WARN] Notion fallback append_images failed: {e2}")

    try:
        append_heading(page_id, "ガイダンス入口", level=2)
        append_bookmark(
            page_id,
            WCN_PORTAL,
            caption="WCN MSMガイダンス（府県・時別）"
        )
    except Exception as e:
        print(f"[WARN] Notion bookmark failed: {e}")

    return page_id

# =============================================================================
# Discord
# =============================================================================

def post_discord(urls, errors, notion_url=""):
    if not discord_url():
        return

    # 画像
    if urls:
        post_discord_item_image_urls(
            webhook_url=discord_url(),
            title="📊 WCN ガイダンス（秋田県）｜MSM府県時別 当日/明日 ＋ 予報分布",
            image_urls=urls,
            notion_url="",
            rjtd="",
            init_jst="",
        )

    # ポータル（テキスト）
    try:
        requests.post(
            discord_url(),
            json={
                "content": f"🔗 ガイダンス入口（WCN・要ログイン）\n{WCN_PORTAL}"
            },
            timeout=10,
        )
    except Exception as e:
        print(e)

    # 完了
    # Discordは速報・確認用に統一するため、Notionリンクは出さない。
    post_discord_complete(
        webhook_url=discord_url(),
        category="Guidance",
        notion_url="",
        attach_count=len(urls),
        errors=errors,
    )


# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Guidance ===")

    base_jst = jst_now()
    prefix = f"{R2_PREFIX}/{base_jst.strftime('%Y%m%d_%H%M')}"

    atts, errors = capture()
    urls, rep = upload(prefix, atts)

    page_id = write_notion(base_jst, prefix, urls, rep, errors, atts)
    notion_url = notion_page_url(page_id) if page_id else ""

    if notion_url:
        print(f"[OK] Notion URL: {notion_url}")

    post_discord(urls, errors, notion_url=notion_url)

    print("=== Done ===")

if __name__ == "__main__":
    main()
