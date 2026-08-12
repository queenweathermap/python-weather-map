# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/advisor_guidance.py
#
# JMA 気象防災アドバイザー ガイダンス帳票 スクリーンショット → Discord(#guidance)
#
# 出力:
#   adv_guid_rain3h.png  MSM 3時間降水量ガイダンス一覧（秋田県）
#   adv_guid_pot.png     MSM 発雷確率ガイダンス（秋田県）
#   adv_guid_snow3h.png  MSM 3時間降雪量ガイダンス（秋田県、5〜10月スキップ）
#   adv_guid_wind.png    MSM 最大風速ガイダンス（秋田県 各地点）
#   adv_cold_temp.png    寒気帳票 気温（秋田）
#   adv_cold_anom.png    寒気帳票 平年差（秋田）
# =============================================================================

from __future__ import annotations

import io
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

# =============================================================================
# 設定
# =============================================================================
JMA_ADV_BASE         = "https://www.jma.go.jp/bosai/advisor"
JMA_ADV_PORTAL       = "https://www.jma.go.jp/bosai/advisor/"
JMA_ADV_USER         = os.environ.get("JMA_ADV_USER",         "").strip()
JMA_ADV_PASS         = os.environ.get("JMA_ADV_PASS",         "").strip()
JMA_ADV_AREA         = os.environ.get("JMA_ADV_AREA",         "秋田県")
JMA_ADV_COLD_STATION = os.environ.get("JMA_ADV_COLD_STATION", "秋田")
JMA_ADV_WAIT_MS      = int(os.environ.get("JMA_ADV_WAIT_MS",  "3000"))
JMA_ADV_VP_W         = int(os.environ.get("JMA_ADV_VP_W",     "1200"))
JMA_ADV_VP_H         = int(os.environ.get("JMA_ADV_VP_H",      "900"))

DISCORD_ADV_WEBHOOK_URL = os.environ.get("DISCORD_ADV_WEBHOOK_URL", "").strip()

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX  = os.environ.get("R2_PREFIX", "adv-guidance").strip().strip("/")

JST = timezone(timedelta(hours=9))

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# =============================================================================
# ユーティリティ
# =============================================================================

def _jst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def _load_fonts():
    try:
        from PIL import ImageFont
        for path in FONT_CANDIDATES:
            if os.path.exists(path):
                try:
                    f_sm = ImageFont.truetype(path, 13)
                    f_md = ImageFont.truetype(path, 14)
                    f_lg = ImageFont.truetype(path, 15)
                    print(f"[INFO] font: {path}")
                    return f_sm, f_md, f_lg
                except Exception:
                    pass
        f = ImageFont.load_default()
        return f, f, f
    except ImportError:
        return None, None, None


def _add_label_banner(img_bytes: bytes, label: str) -> bytes:
    """画像上部にラベルバナーを追加する。"""
    try:
        from PIL import Image, ImageDraw
        img = Image.open(io.BytesIO(img_bytes))
        banner_h = 34
        new_img = Image.new("RGB", (img.width, img.height + banner_h), (45, 90, 145))
        draw = ImageDraw.Draw(new_img)
        f_sm, _, _ = _load_fonts()
        draw.text((12, (banner_h - 14) // 2), label, fill=(255, 255, 255), font=f_sm)
        new_img.paste(img, (0, banner_h))
        buf = io.BytesIO()
        new_img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] label追加失敗: {e}")
        return img_bytes


def _split_wind_two_cols(img_bytes: bytes) -> bytes:
    """風速帳票（秋田県）を 沿岸 / 内陸 で垂直分割して横2列に並べる。
    分割点: 左端列の色変化（沿岸→内陸 の section header row）を検出。
    検出失敗時は縦半分で分割。
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        W, H = img.size
        px = img.load()

        split_y = None
        scan_xs = [2, 4, 6, 8, 10]
        prev_colors = [(px[x, 0][0], px[x, 0][1], px[x, 0][2]) for x in scan_xs]
        for y in range(10, H - 10):
            cur_colors = [(px[x, y][0], px[x, y][1], px[x, y][2]) for x in scan_xs]
            diffs = [abs(c[0]-p[0])+abs(c[1]-p[1])+abs(c[2]-p[2])
                     for c, p in zip(cur_colors, prev_colors)]
            if sum(diffs) > 300 and y > H * 0.3:
                split_y = y
                break
            prev_colors = cur_colors

        if split_y is None:
            split_y = H // 2

        top = img.crop((0, 0, W, split_y))
        bot = img.crop((0, split_y, W, H))
        new_img = Image.new("RGB", (W * 2, max(top.height, bot.height)), (255, 255, 255))
        new_img.paste(top, (0, 0))
        new_img.paste(bot, (W, 0))

        buf = io.BytesIO()
        new_img.save(buf, format="PNG", optimize=True)
        print(f"[INFO] wind split at y={split_y} (H={H})")
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] wind split 失敗: {e}")
        return img_bytes


# =============================================================================
# スクリーンショット
# =============================================================================

def screenshot_jma_advisor() -> List[Tuple[str, bytes]]:
    """気象防災アドバイザーサイトのガイダンス帳票をスクリーンショット。"""
    if not (JMA_ADV_USER and JMA_ADV_PASS):
        print("[SKIP] JMA_ADV_USER/PASS 未設定 — アドバイザー スクリーンショットをスキップ")
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[WARN] playwright 未インストール")
        return []

    results: List[Tuple[str, bytes]] = []
    month = _jst_now().month

    def _wait(page) -> None:
        page.wait_for_timeout(JMA_ADV_WAIT_MS)

    def _select_area(page, area: str) -> None:
        sel = page.locator("select").first
        opts = sel.locator("option").all_text_contents()
        print(f"[DEBUG] area opts={opts}")
        if area in opts:
            sel.select_option(label=area)
            return
        PREF_TO_REGION = {
            "北海道": "北海道地方",
            "青森県": "東北地方", "岩手県": "東北地方", "宮城県": "東北地方",
            "秋田県": "東北地方", "山形県": "東北地方", "福島県": "東北地方",
            "茨城県": "関東甲信地方", "栃木県": "関東甲信地方", "群馬県": "関東甲信地方",
            "埼玉県": "関東甲信地方", "東京都": "関東甲信地方", "千葉県": "関東甲信地方",
            "神奈川県": "関東甲信地方", "長野県": "関東甲信地方", "山梨県": "関東甲信地方",
            "新潟県": "北陸地方", "富山県": "北陸地方", "石川県": "北陸地方", "福井県": "北陸地方",
            "静岡県": "東海地方", "愛知県": "東海地方", "岐阜県": "東海地方", "三重県": "東海地方",
        }
        region = PREF_TO_REGION.get(area)
        if region and region in opts:
            sel.select_option(label=region)
            print(f"[INFO] エリア: {area} → {region}")
            return
        short = area.replace("県","").replace("都","").replace("府","")
        matched = [o for o in opts if short in o]
        if matched:
            sel.select_option(label=matched[0])
            print(f"[INFO] エリア部分一致: {matched[0]}")
        else:
            print(f"[WARN] エリア選択失敗: {area} opts={opts}")

    def _shot_body(page, label: str) -> bytes:
        raw = page.locator("body").screenshot()
        return _add_label_banner(raw, label)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            http_credentials={"username": JMA_ADV_USER, "password": JMA_ADV_PASS},
            viewport={"width": JMA_ADV_VP_W, "height": JMA_ADV_VP_H},
        )
        page = ctx.new_page()

        # ── guid_table: 降水・発雷・降雪 ────────────────────────────
        GUID_TABLE_URL = f"{JMA_ADV_BASE}/guid_table.html"
        for elem_value, fname, lbl, skip in [
            ("rain3", "adv_guid_rain3h.png", "MSM 3時間降水量ガイダンス（秋田県）", False),
            ("pot",   "adv_guid_pot.png",    "MSM 発雷確率ガイダンス（秋田県）",   False),
            ("snow3", "adv_guid_snow3h.png", "MSM 3時間降雪量ガイダンス（秋田県）", 5 <= month <= 10),
        ]:
            if skip:
                print(f"[SKIP] {fname}（降雪量 5〜10月）")
                continue
            try:
                page.goto(GUID_TABLE_URL, wait_until="networkidle", timeout=60_000)
                _wait(page)
                _select_area(page, JMA_ADV_AREA)
                try:
                    page.locator("span.model").filter(has_text="MSM").first.click(timeout=5_000)
                    _wait(page)
                except Exception:
                    pass
                try:
                    page.locator("select").nth(1).select_option(value=elem_value)
                except Exception:
                    for sel in page.locator("select").all():
                        try:
                            sel.select_option(value=elem_value)
                            break
                        except Exception:
                            pass
                _wait(page)
                raw = _shot_body(page, lbl)
                results.append((fname, raw))
                print(f"[OK] {fname}  {len(raw):,} bytes")
            except Exception as e:
                print(f"[WARN] {fname} 撮影失敗: {e}")

        # ── guid_table_wind: 最大風速 ────────────────────────────────
        try:
            WIND_URL = f"{JMA_ADV_BASE}/guid_table_wind.html"
            page.goto(WIND_URL, wait_until="networkidle", timeout=60_000)
            _wait(page)
            _select_area(page, JMA_ADV_AREA)
            _wait(page)
            pref_short = JMA_ADV_AREA.replace("県","").replace("都","").replace("府","")
            sel = page.locator("select").first
            opts = sel.locator("option").all_text_contents()
            print(f"[DEBUG] wind opts after region: {opts}")
            pref_opts = [o for o in opts if pref_short in o and o.startswith("　")]
            if pref_opts:
                sel.select_option(label=pref_opts[0])
                print(f"[INFO] wind 県選択: {pref_opts[0].strip()}")
                _wait(page)
            else:
                print(f"[WARN] wind 県オプション見つからず（{pref_short}）: {opts}")
            try:
                page.locator("span.model").filter(has_text="MSM").first.click(timeout=5_000)
                _wait(page)
            except Exception:
                pass
            raw_full = page.locator("body").screenshot()
            img = _add_label_banner(raw_full, f"MSM 最大風速ガイダンス（{JMA_ADV_AREA} 各地点）")
            results.append(("adv_guid_wind.png", img))
            print(f"[OK] adv_guid_wind.png  {len(img):,} bytes")
        except Exception as e:
            print(f"[WARN] adv_guid_wind 撮影失敗: {e}")

        # ── cold_table: 寒気帳票 気温 / 平年差 ──────────────────────
        COLD_URL = f"{JMA_ADV_BASE}/cold_table.html"
        try:
            page.goto(COLD_URL, wait_until="networkidle", timeout=60_000)
            _wait(page)
            station = JMA_ADV_COLD_STATION
            page.locator(f"th.clickable:text-is('{station}')").first.click(timeout=10_000)
            _wait(page)
            page.locator("#display-false").dispatch_event("mousedown")
            _wait(page)
            raw = _shot_body(page, f"寒気帳票 気温（{station}）")
            results.append(("adv_cold_temp.png", raw))
            print(f"[OK] adv_cold_temp.png  {len(raw):,} bytes")
            page.locator("#display-true").dispatch_event("mousedown")
            _wait(page)
            raw = _shot_body(page, f"寒気帳票 平年差（{station}）")
            results.append(("adv_cold_anom.png", raw))
            print(f"[OK] adv_cold_anom.png  {len(raw):,} bytes")
        except Exception as e:
            print(f"[WARN] adv_cold 撮影失敗: {e}")

        browser.close()

    return results


# =============================================================================
# R2 アップロード
# =============================================================================

def _upload_r2(items: List[Tuple[str, bytes]]) -> List[str]:
    if not R2_ENABLE:
        return []
    try:
        from module.utils.r2_utils import put_bytes, make_url
    except ImportError:
        print("[WARN] r2_utils not available")
        return []

    day_hm = _jst_now().strftime("%Y%m%d/%H%M")
    urls: List[str] = []
    for fname, data in items:
        key = f"{R2_PREFIX}/{day_hm}/{fname}"
        try:
            put_bytes(key, data, content_type="image/png")
            urls.append(make_url(key))
            print(f"[OK] R2 upload: {key}")
        except Exception as e:
            print(f"[WARN] R2 upload {key}: {e}")
            urls.append("")
    return urls


# =============================================================================
# Discord 投稿
# =============================================================================

def _post_images_bulk(images: List[Tuple[str, bytes]], content: str = "") -> None:
    """(filename, bytes) リストを最大10枚ずつ Discord に投稿する。"""
    if not DISCORD_ADV_WEBHOOK_URL or not images:
        return

    chunk_size = 10
    for chunk_start in range(0, len(images), chunk_size):
        chunk = images[chunk_start: chunk_start + chunk_size]
        boundary = f"----AdvisorGuidanceBulk{chunk_start}"
        payload = {
            "content": content if chunk_start == 0 else "",
            "attachments": [{"id": i, "filename": fn} for i, (fn, _) in enumerate(chunk)],
        }

        def _part_json(d: str) -> bytes:
            h = (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="payload_json"\r\n'
                 f"Content-Type: application/json\r\n\r\n")
            return h.encode() + d.encode() + b"\r\n"

        def _part_file(i: int, data: bytes, name: str) -> bytes:
            h = (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="files[{i}]"; filename="{name}"\r\n'
                 f"Content-Type: image/png\r\n\r\n")
            return h.encode() + data + b"\r\n"

        body = _part_json(json.dumps(payload))
        for i, (fn, data) in enumerate(chunk):
            body += _part_file(i, data, fn)
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            DISCORD_ADV_WEBHOOK_URL, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent":   "akita-advisor-guidance-bot/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"[OK] Discord bulk HTTP {r.status} ({len(chunk)} files)")
        except Exception as e:
            print(f"[ERR] Discord bulk post: {e}")


# =============================================================================
# main
# =============================================================================

def main() -> None:
    print("=== Start Advisor Guidance ===")

    images = screenshot_jma_advisor()
    if not images:
        print("[INFO] 画像なし — スキップ")
        print("=== Done ===")
        return

    _upload_r2(images)

    _post_images_bulk(
        images,
        content="**気象防災アドバイザー ガイダンス帳票**\n🔗 [気象防災アドバイザー向け資料集](<{}>)".format(JMA_ADV_PORTAL),
    )

    print("=== Done ===")


if __name__ == "__main__":
    main()
