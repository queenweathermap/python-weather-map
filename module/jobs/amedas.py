# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/amedas.py
#
# WCN（気象キャスターネットワーク）アメダス一覧:
#   HTML → スクショ → JPG/PNG → R2一時保存 → Notion取り込み → Discord(#amedas)
#
# 撮影対象（いずれも「府県選択→決定」で右ページが変わる方式）:
#   ① アメダス積算降水量  totalamedas.html
#   ② アメダス気温（最高） alltemp.html  要素=最高気温
#   ③ アメダス気温（最低） alltemp.html  要素=最低気温
#
# 範囲は「秋田県」のみ（他ジョブと同じ秋田中心）。全国一覧から秋田県セクションを
# 切り出す。配信は 朝3時 / 午後3時（JST）の2回。
#
# 方針:
#   ・Notion = 正本
#   ・R2 = 21日保存の一時置き場
#   ・Discord = ビュー
#   ・入口リンクはテキスト投稿
# =============================================================================

from __future__ import annotations

import io
import os
import re
import time
import requests

from datetime import datetime, timezone, timedelta
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

OUTPUT_DIR = "/tmp/jma_amedas"

JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "90"))
R2_ENABLE = os.environ.get("R2_ENABLE", "1") in ("1", "true", "yes")
R2_PREFIX = os.environ.get("R2_PREFIX", "amedas")

VIEWPORT_WIDTH = int(os.environ.get("AMEDAS_VIEWPORT_WIDTH", "1280"))
VIEWPORT_HEIGHT = int(os.environ.get("AMEDAS_VIEWPORT_HEIGHT", "1000"))
WAIT_MS = int(os.environ.get("AMEDAS_WAIT_MS", "2500"))

NOTION_IMPORT_IMAGES = os.environ.get("NOTION_IMPORT_IMAGES", "0").lower() in ("1", "true", "yes", "on")
NOTION_IMPORT_TIMEOUT_SECONDS = int(os.environ.get("NOTION_IMPORT_TIMEOUT_SECONDS", "180"))
NOTION_IMPORT_POLL_SECONDS = float(os.environ.get("NOTION_IMPORT_POLL_SECONDS", "2.0"))

Attachment = Tuple[str, bytes, str]

# =============================================================================
# WCN会員ページ。Basic認証（WEATHERCASTER_USER/PASS）。
# 直URLは別府県に戻るため、各ページで「府県選択→決定」して秋田を描画させる。
# =============================================================================
WCN_BASE = os.environ.get(
    "WCN_BASE", "https://www.weathercaster.jp/web/member_only/weather-data")
WCN_PREF = os.environ.get("WCN_PREF", "秋田県")

AMEDAS_TOTAL_URL = f"{WCN_BASE}/amedas/totalamedas.html"
AMEDAS_TEMP_URL = f"{WCN_BASE}/amedas/alltemp.html"
AMEDAS_RANKING_URL = f"{WCN_BASE}/amedas/ranking.html"

# 撮影対象。
#   element = 要素選択（最高気温/最低気温）。None は要素選択なし。
#   scope   = "akita" … 秋田県セクションを切り出す / "all" … 右ページ全体（全国）を撮る
AMEDAS_TARGETS = [
    {
        "name": "amedas_total_precip",
        "label": "アメダス積算降水量",
        "url": AMEDAS_TOTAL_URL,
        "element": None,
        "scope": "akita",
    },
    {
        "name": "amedas_temp_max",
        "label": "アメダス気温(最高)",
        "url": AMEDAS_TEMP_URL,
        "element": "最高気温",
        "scope": "akita",
    },
    {
        "name": "amedas_temp_min",
        "label": "アメダス気温(最低)",
        "url": AMEDAS_TEMP_URL,
        "element": "最低気温",
        "scope": "akita",
    },
    {
        "name": "amedas_ranking",
        "label": "アメダスランキング(全国)",
        "url": AMEDAS_RANKING_URL,
        "element": None,
        "scope": "all",
    },
]

# 全国一覧ページから「秋田県」セクションの矩形（CSS px・ページ座標）を求めるJS。
# 「topへ」リンクを持つ府県見出しの位置を上から並べ、秋田県の見出し〜次の見出し
# 直前までを切り出し範囲とする。見つからなければ null（→ full_page にフォールバック）。
CLIP_JS = r"""
(pref) => {
  const norm = s => (s || '').replace(/\s/g, '');
  const want = norm(pref);                 // 秋田県
  const wantShort = want.replace('県', '').replace('府', '').replace('地方', ''); // 秋田

  // 「topへ」リンク＝各府県見出しの目印
  const tops = Array.from(document.querySelectorAll('a'))
    .filter(a => /top/i.test(a.textContent || '') && /へ/.test(a.textContent || ''));

  const heads = tops.map(a => {
    // top へ リンクを含む見出し行（府県名テキストを含む親）まで遡る
    let el = a;
    for (let i = 0; i < 5 && el.parentElement; i++) {
      el = el.parentElement;
      const t = norm(el.textContent);
      if (t.length > 2) break;
    }
    const r = el.getBoundingClientRect();
    return { y: r.top + window.scrollY, text: norm(el.textContent) };
  }).sort((a, b) => a.y - b.y);

  if (!heads.length) return null;

  let idx = heads.findIndex(h => h.text.includes(want) || h.text.includes(wantShort));
  if (idx < 0) return null;

  const top = Math.max(0, heads[idx].y - 10);
  const bottom = (idx + 1 < heads.length)
    ? heads[idx + 1].y - 6
    : document.body.scrollHeight;
  const width = Math.max(
    document.documentElement.scrollWidth,
    document.body.scrollWidth
  );
  return { x: 0, y: top, width: width, height: Math.max(60, bottom - top) };
}
"""

# =============================================================================
# Utility
# =============================================================================

def jst_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))


def png_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def discord_url():
    return os.getenv("DISCORD_AMEDAS_WEBHOOK_URL", "")


def notion_page_url(page_id: str) -> str:
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# フォーム操作（要素選択・府県選択・決定）
# =============================================================================

def _check_element(page, element_label) -> bool:
    """要素選択（最高気温/最低気温）のラジオを選ぶ。複数戦略で堅牢に。"""
    if not element_label:
        return True
    strategies = [
        lambda: page.get_by_label(element_label, exact=False).first.check(timeout=4000),
        lambda: page.get_by_text(element_label, exact=False).first.click(timeout=4000),
    ]
    for s in strategies:
        try:
            s()
            return True
        except Exception:
            continue
    print(f"[WARN] 要素選択に失敗: {element_label}")
    return False


def _select_pref_dropdown(page, pref) -> bool:
    """府県が <select> なら選ぶ。成功したらフィルタ式とみなす。"""
    try:
        sels = page.locator("select")
        n = sels.count()
        for i in range(n):
            try:
                sels.nth(i).select_option(label=pref, timeout=2000)
                return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _click_decide(page) -> bool:
    """「決定」ボタン（空白入り "決 定" にも対応）を押す。"""
    try:
        page.get_by_role("button", name=re.compile(r"決\s*定")).first.click(timeout=3000)
        return True
    except Exception:
        pass
    try:
        page.locator(
            "input[type=submit], input[type=button], button"
        ).filter(has_text=re.compile(r"決\s*定")).first.click(timeout=3000)
        return True
    except Exception:
        pass
    return False


def _click_pref_link(page, pref) -> bool:
    """府県リンク（アンカー）をクリックして秋田県セクションへスクロールさせる。"""
    for fn in (
        lambda: page.get_by_role("link", name=re.compile(re.escape(pref))).first.click(timeout=4000),
        lambda: page.get_by_text(pref, exact=False).first.click(timeout=4000),
    ):
        try:
            fn()
            return True
        except Exception:
            continue
    return False


def _grab_full_image(page, label) -> Image.Image:
    """右ページ全体（全国）の PIL Image を返す。
    data_area iframe があればその body、無ければページ全体（full_page）。クロップしない。
    """
    fr = page.frame(name="data_area")
    if fr is not None:
        try:
            png = fr.locator("body").screenshot(type="png")
            print(f"[INFO] {label}: iframe data_area を撮影（全国）")
            return Image.open(io.BytesIO(png)).convert("RGB")
        except Exception as e:
            print(f"[WARN] {label}: iframe撮影に失敗: {e}")
    png_full = page.screenshot(full_page=True, type="png")
    img = Image.open(io.BytesIO(png_full)).convert("RGB")
    print(f"[INFO] {label}: full_page（全国） {img.size}")
    return img


def _grab_akita_image(page, label) -> Image.Image:
    """秋田県の表だけを切り出した PIL Image を返す。
    1) data_area iframe（フィルタ式）があればその body を撮る
    2) 全国ページなら full_page を撮り、秋田県セクション矩形でクロップ
    3) 矩形が見つからなければ full_page をそのまま返す
    deviceScaleFactor=1 前提なので CSS px とスクショpx は一致する。
    """
    fr = page.frame(name="data_area")
    if fr is not None:
        try:
            png = fr.locator("body").screenshot(type="png")
            print(f"[INFO] {label}: iframe data_area を撮影")
            return Image.open(io.BytesIO(png)).convert("RGB")
        except Exception as e:
            print(f"[WARN] {label}: iframe撮影に失敗: {e}")

    png_full = page.screenshot(full_page=True, type="png")
    img = Image.open(io.BytesIO(png_full)).convert("RGB")

    clip = None
    try:
        clip = page.evaluate(CLIP_JS, WCN_PREF)
    except Exception as e:
        print(f"[WARN] {label}: clip評価に失敗: {e}")

    if clip and clip.get("height", 0) > 60:
        x = max(0, int(clip["x"]))
        y = max(0, int(clip["y"]))
        w = int(clip["width"])
        h = int(clip["height"])
        img = img.crop((x, y, min(img.width, x + w), min(img.height, y + h)))
        print(f"[INFO] {label}: 秋田県セクションをクロップ {img.size}")
    else:
        print(f"[INFO] {label}: 秋田県セクション未検出 → full_page {img.size}")

    return img


# =============================================================================
# スクショ
# =============================================================================

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
            device_scale_factor=1,
        )
        page = context.new_page()

        for t in AMEDAS_TARGETS:
            name, label, url, element = t["name"], t["label"], t["url"], t["element"]
            scope = t.get("scope", "akita")
            try:
                print(f"[INFO] {label}")
                page.goto(url, wait_until="networkidle", timeout=60000)

                # 要素選択（最高/最低）→（秋田のみ府県選択）→ 決定
                _check_element(page, element)
                dropdown_ok = True
                if scope == "akita":
                    dropdown_ok = _select_pref_dropdown(page, WCN_PREF)
                _click_decide(page)

                try:
                    page.wait_for_load_state("networkidle", timeout=60000)
                except Exception:
                    pass
                page.wait_for_timeout(WAIT_MS)

                if scope == "akita":
                    # ドロップダウンで絞り込めない（リンク式）の場合は、府県アンカーへ移動
                    if not dropdown_ok:
                        _click_pref_link(page, WCN_PREF)
                        page.wait_for_timeout(800)
                    # 秋田が描画されたか軽く待つ（失敗しても続行）
                    try:
                        page.get_by_text(WCN_PREF[:2], exact=False).first.wait_for(timeout=10000)
                    except Exception:
                        pass

                body_text = page.locator("body").inner_text(timeout=5000)
                if "Authentication Failed" in body_text or "Unauthorized" in body_text:
                    errors.append(f"{label}: authentication failed")
                    continue

                if scope == "akita":
                    img = _grab_akita_image(page, label)
                else:
                    img = _grab_full_image(page, label)
                atts.append((f"{name}.png", png_bytes(img), "image/png"))

            except Exception as e:
                errors.append(f"{label}: {e}")

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

    title = f"Amedas / {base_jst.strftime('%Y%m%d %H:%M')}"

    page_id = create_db_row(
        title=title,
        category="Amedas",
        init_jst_iso=base_jst.isoformat(),
        memo="\n".join(errors),
        rjtd="",
        prefix=prefix,
        r2_url=rep or "",
        autogen=True,
        icon_emoji="🌡️",
    )

    if not page_id:
        return None

    time.sleep(1)

    try:
        append_heading(page_id, "アメダス（秋田県）", level=2)

        if urls:
            if NOTION_IMPORT_IMAGES:
                items = []
                for idx, url in enumerate(urls):
                    if idx < len(atts):
                        fname, _blob, mime = atts[idx]
                    else:
                        fname, mime = f"amedas_{idx + 1:02d}.png", "image/png"
                    items.append((fname, url, mime or "image/png"))

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

        try:
            if urls:
                append_images(page_id, urls)
        except Exception as e2:
            print(f"[WARN] Notion fallback append_images failed: {e2}")

    try:
        append_heading(page_id, "アメダス入口", level=2)
        append_bookmark(page_id, AMEDAS_TOTAL_URL, caption="WCN アメダス積算降水量")
        append_bookmark(page_id, AMEDAS_TEMP_URL, caption="WCN アメダス気温（最高/最低）")
        append_bookmark(page_id, AMEDAS_RANKING_URL, caption="WCN アメダスランキング（全国）")
    except Exception as e:
        print(f"[WARN] Notion bookmark failed: {e}")

    return page_id

# =============================================================================
# Discord
# =============================================================================

def post_discord(urls, errors, notion_url=""):
    if not discord_url():
        return

    # 画像（積算降水量・最高気温・最低気温）
    if urls:
        post_discord_item_image_urls(
            webhook_url=discord_url(),
            title="🌡️ アメダス｜秋田県(積算降水量・最高/最低気温) ＋ ランキング(全国)",
            image_urls=urls,
            notion_url="",
            rjtd="",
            init_jst="",
        )

    # 入口（テキスト）
    try:
        requests.post(
            discord_url(),
            json={
                "content": (
                    "🔗 アメダス入口（WCN・要ログイン）\n"
                    f"・積算降水量: {AMEDAS_TOTAL_URL}\n"
                    f"・気温(最高/最低): {AMEDAS_TEMP_URL}\n"
                    f"・ランキング(全国): {AMEDAS_RANKING_URL}"
                )
            },
            timeout=10,
        )
    except Exception as e:
        print(e)

    # 完了
    post_discord_complete(
        webhook_url=discord_url(),
        category="Amedas",
        notion_url="",
        attach_count=len(urls),
        errors=errors,
    )


# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Amedas ===")

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
