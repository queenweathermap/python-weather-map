# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/guidance.py
#
# WCN(Weathercaster.jp)会員ページを Playwright でスクリーンショットし、
# MSM時別ガイダンス・分布予報・週間ガイダンス・気象庁予報を Discord に投稿する。
# =============================================================================

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import List, Tuple

# =============================================================================
# 設定
# =============================================================================
DISCORD_GUIDANCE_WEBHOOK_URL = os.environ.get("DISCORD_GUIDANCE_WEBHOOK_URL", "")

WCN_KISHO_URL = "https://www.weathercaster.jp/member/member_only/kisho_shiryo/"

# =============================================================================
# WCN スクリーンショット設定
# =============================================================================
WCN_USER      = os.environ.get("WEATHERCASTER_USER", "").strip()
WCN_PASS      = os.environ.get("WEATHERCASTER_PASS", "").strip()
WCN_PREF      = os.environ.get("WCN_PREF", "秋田県")
WCN_WAIT_MS     = int(os.environ.get("GUIDANCE_WAIT_MS", "2500"))
WCN_VP_W        = int(os.environ.get("GUIDANCE_VIEWPORT_WIDTH",  "1600"))
WCN_VP_H        = int(os.environ.get("GUIDANCE_VIEWPORT_HEIGHT", "1200"))
# MSM タイル設定（縦長画像を横並びに分割）
WCN_MSM_COLS    = int(os.environ.get("WCN_MSM_COLS",      "5"))   # 列数
WCN_MSM_HDR_PX  = int(os.environ.get("WCN_MSM_HEADER_PX", "0"))   # ヘッダー高さ(px)。0=自動推定

# MSM 府県時別
WCN_MSM_URL   = os.environ.get(
    "WCN_MSM_URL",
    "https://www.weathercaster.jp/web/member_only/weather-data/msm_guidance/gui_ken_hour.html",
)
# 分布予報・市町村: (ファイル名suffix, select value, 表示名)
WCN_BUNPU_URL = os.environ.get(
    "WCN_BUNPU_URL",
    "https://www.weathercaster.jp/web/member_only/weather-data/jma_yoho/bunpu_office.html",
)
WCN_BUNPU_FACTORS = [
    ("tenki",  "0"),  # 天気
    ("rain3h", "1"),  # 3時間降水量
    ("snow3h", "2"),  # 3時間降雪量
    ("temp",   "3"),  # 気温
]
# 週間ガイダンス日データ
WCN_WEEK_URL  = os.environ.get(
    "WCN_WEEK_URL",
    "https://www.weathercaster.jp/web/member_only/weather-data/week_guidance/gui_all_daily.html",
)
WCN_WEEK_FACTORS = [
    ("tmax",  "0"),  # 最高気温
    ("tmin",  "1"),  # 最低気温
    ("rain",  "2"),  # 日降水量
]

# 気象庁 秋田県天気予報（公開ページ）
JMA_FORECAST_URL = os.environ.get(
    "JMA_FORECAST_URL",
    "https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code=050000",
)


R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
R2_PREFIX  = os.environ.get("R2_PREFIX", "guidance").strip().strip("/")

JST = timezone(timedelta(hours=9))

COAST_CODE  = "050010"
INLAND_CODE = "050020"


# 短期予報の温度代表地点

# 秋田県 市町村一覧（予報地域, 気温代表観測点）
#   予報地域: COAST_CODE=沿岸 / INLAND_CODE=内陸
#   気温代表: 32402=秋田 / 32126=鷹巣 / 32596=横手
AKITA_MUNICIPALITIES: List[Tuple[str, str, str]] = [
    # 沿岸
    ("秋田市",    COAST_CODE, "32402"),
    ("潟上市",    COAST_CODE, "32402"),
    ("男鹿市",    COAST_CODE, "32402"),
    ("五城目町",  COAST_CODE, "32402"),
    ("八郎潟町",  COAST_CODE, "32402"),
    ("井川町",    COAST_CODE, "32402"),
    ("大潟村",    COAST_CODE, "32402"),
    ("能代市",    COAST_CODE, "32402"),
    ("三種町",    COAST_CODE, "32402"),
    ("八峰町",    COAST_CODE, "32402"),
    ("由利本荘市",COAST_CODE, "32402"),
    ("にかほ市",  COAST_CODE, "32402"),
    # 内陸
    ("大館市",    INLAND_CODE, "32126"),
    ("小坂町",    INLAND_CODE, "32126"),
    ("北秋田市",  INLAND_CODE, "32126"),
    ("上小阿仁村",INLAND_CODE, "32126"),
    ("藤里町",    INLAND_CODE, "32126"),
    ("鹿角市",    INLAND_CODE, "32126"),
    ("仙北市",    INLAND_CODE, "32596"),
    ("大仙市",    INLAND_CODE, "32596"),
    ("横手市",    INLAND_CODE, "32596"),
    ("湯沢市",    INLAND_CODE, "32596"),
    ("美郷町",    INLAND_CODE, "32596"),
    ("羽後町",    INLAND_CODE, "32596"),
    ("東成瀬村",  INLAND_CODE, "32596"),
]

# 画像スタイル
C_TITLE_BG  = (45,  90, 145)
C_TITLE_FG  = (255, 255, 255)
C_HEADER_BG = (85, 140, 200)
C_HEADER_FG = (255, 255, 255)
C_ROW_ODD   = (255, 255, 255)
C_ROW_EVEN  = (238, 246, 255)
C_BORDER    = (190, 205, 220)
C_TEXT      = (30,  30,  30)

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# =============================================================================
# ユーティリティ
# =============================================================================

def _jst_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


# =============================================================================
# フォント
# =============================================================================

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


# =============================================================================
# WCN スクリーンショット（Playwright）
# =============================================================================

def _wcn_submit_and_wait(page, form_frame, factor_select: str, factor_value: str) -> None:
    """form_area の factorNo/fuken select を選んで決定し、framenavigated を待つ。"""
    form_frame.locator(f'select[name="{factor_select}"]').select_option(value=factor_value)
    with page.expect_event("framenavigated", timeout=15_000):
        form_frame.locator('input[type="submit"][name="dat"]').click()
    page.wait_for_timeout(WCN_WAIT_MS)


def _wcn_click_pref(data_frame, pref: str) -> None:
    """data_area iframe 内の府県ナビリンクをクリックして秋田県セクションへジャンプ。"""
    link = data_frame.locator(f"a:text('{pref}')").first
    if link.count() > 0:
        link.click()
        import time; time.sleep(0.4)


def _tile_columns(img_bytes: bytes, n_cols: int = 5, header_px: int = 60) -> bytes:
    """縦長画像をステーション境界で切って n_cols 列に横並びする。

    ステーションヘッダー行（オレンジ/赤系）を検出し、
    等分割目標に最も近い境界で切ることで途中切れを防ぐ。
    header_px 行分をヘッダーとして各タイルに複製する。
    """
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(img_bytes))
        W, H = img.size
        px = img.load()

        # ── ステーション境界行を検出 ──────────────────────────
        # WCN MSM の時刻ラベル行 = 肌色/ピンク系
        # 色プロファイル実測値: RGB(255,228,225)
        # 条件: R>240, G>210, B>210, R が最大, G≈B（白との区別: R>G が必要）
        sample_xs = [max(1, W * k // 8) for k in range(1, 8)]  # 7点サンプル

        def _is_time_label_row(y: int) -> bool:
            cnt = 0
            for x in sample_xs:
                try:
                    r, g, b = px[x, y][0], px[x, y][1], px[x, y][2]
                    # 肌色/ピンク: R が高くて G・B より大きく、かつ G と B が近い
                    if r > 240 and g > 210 and b > 210 and r > g and r > b and abs(int(g) - int(b)) < 25:
                        cnt += 1
                except Exception:
                    pass
            return cnt >= 4

        raw_bounds: list[int] = []
        prev_pink = False
        for y in range(header_px, H):
            cur = _is_time_label_row(y)
            if cur and not prev_pink:
                raw_bounds.append(y)
            prev_pink = cur

        # 同一ステーション内の近接ピンク行（100px未満）は最初の1行だけ残す
        station_bounds: list[int] = []
        prev_b = -(header_px + 200)
        for b in raw_bounds:
            if b - prev_b > 100:
                station_bounds.append(b)
                prev_b = b

        print(f"[INFO] tile_columns: detected {len(station_bounds)} station boundaries")

        # ── 等分割に最も近い境界で分割点を決定 ──────────────
        body_h = H - header_px
        if not station_bounds:
            # 境界未検出 → 等分割にフォールバック
            print("[WARN] tile_columns: no boundaries detected, using equal-interval split")
            split_ys = [header_px + i * body_h // n_cols for i in range(n_cols)] + [H]
        else:
            split_ys: list[int] = [header_px]
            for col in range(1, n_cols):
                target_y = header_px + col * body_h // n_cols
                # target_y を超えない中で最も近い station boundary
                candidates = [b for b in station_bounds if b <= target_y]
                if candidates:
                    best = max(candidates)
                else:
                    best = header_px
                if best != split_ys[-1]:
                    split_ys.append(best)
            split_ys.append(H)

        # 分割数が n_cols より少なくなった場合は等分割で補完
        if len(split_ys) - 1 < n_cols:
            print(f"[WARN] tile_columns: only {len(split_ys)-1} splits found, falling back to equal-interval")
            split_ys = [header_px + i * body_h // n_cols for i in range(n_cols)] + [H]

        # 実際の列数（境界が足りない場合は減る可能性あり）
        actual_cols = len(split_ys) - 1
        tile_heights = [split_ys[i + 1] - split_ys[i] for i in range(actual_cols)]
        max_tile_h = max(tile_heights) if tile_heights else body_h

        hdr_img = img.crop((0, 0, W, header_px))
        new_w = W * actual_cols
        new_h = header_px + max_tile_h
        tiled = Image.new("RGB", (new_w, new_h), (255, 255, 255))

        for i in range(actual_cols):
            x = i * W
            tiled.paste(hdr_img, (x, 0))
            strip = img.crop((0, split_ys[i], W, split_ys[i + 1]))
            tiled.paste(strip, (x, header_px))

        buf = _io.BytesIO()
        tiled.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] tile_columns 失敗: {e}")
        return img_bytes


def _add_label_banner(img_bytes: bytes, label: str) -> bytes:
    """画像上部にラベルバナーを追加する。Pillow 未インストール時は元画像をそのまま返す。"""
    try:
        from PIL import Image, ImageDraw
        import io as _io
        img = Image.open(_io.BytesIO(img_bytes))
        banner_h = 34
        new_img = Image.new("RGB", (img.width, img.height + banner_h), (45, 90, 145))
        draw = ImageDraw.Draw(new_img)
        f_sm, _, _ = _load_fonts()
        draw.text((12, (banner_h - 14) // 2), label, fill=(255, 255, 255), font=f_sm)
        new_img.paste(img, (0, banner_h))
        buf = _io.BytesIO()
        new_img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] label追加失敗: {e}")
        return img_bytes


def screenshot_wcn_all() -> List[Tuple[str, bytes]]:
    """WCN 各ページをスクリーンショットして [(filename, bytes), ...] を返す。

    取得画像:
      wcn_msm_d0.png       MSM 府県時別 秋田県 今日
      wcn_msm_d1.png       MSM 府県時別 秋田県 明日
      wcn_bunpu_tenki.png  分布予報 天気
      wcn_bunpu_rain3h.png 分布予報 3時間降水量
      wcn_bunpu_snow3h.png 分布予報 3時間降雪量
      wcn_bunpu_temp.png   分布予報 気温
      wcn_week_tmax.png    週間ガイダンス 最高気温
      wcn_week_tmin.png    週間ガイダンス 最低気温
      wcn_week_rain.png    週間ガイダンス 日降水量
    """
    if not (WCN_USER and WCN_PASS):
        print("[SKIP] WEATHERCASTER_USER/PASS 未設定 — WCN スクリーンショットをスキップ")
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[WARN] playwright 未インストール — WCN スクリーンショットをスキップ")
        return []

    results: List[Tuple[str, bytes]] = []

    def _shot_viewport(page) -> bytes:
        """data_area iframe の表示域（秋田セクションへスクロール後）を撮影。"""
        return page.locator('iframe[name="data_area"]').screenshot()

    def _shot_fullbody(page) -> bytes:
        """data_area iframe を scrollHeight まで拡張して全体撮影。"""
        df = page.frame(name="data_area")
        if not df:
            raise RuntimeError("data_area not found")
        # iframe の高さを body の実スクロール高さに合わせてから撮影
        scroll_h = df.evaluate("document.body.scrollHeight")
        page.evaluate(
            f"document.querySelector('iframe[name=\"data_area\"]').style.height = '{scroll_h}px'"
        )
        page.wait_for_timeout(200)
        return page.locator('iframe[name="data_area"]').screenshot()

    def _grab_form_data(page, base_url: str, select_name: str,
                        factors: List[Tuple[str, str]], fname_prefix: str,
                        labels: List[str], scroll_to_pref: bool = False) -> None:
        """共通: フォームで要素選択 → 決定 → data_area 撮影 を factors 分繰り返す。"""
        for (suffix, value), lbl in zip(factors, labels):
            try:
                page.goto(base_url, wait_until="networkidle", timeout=60_000)
                ff = page.frame(name="form_area")
                if not ff:
                    raise RuntimeError("form_area not found")
                _wcn_submit_and_wait(page, ff, select_name, value)
                if scroll_to_pref:
                    df = page.frame(name="data_area")
                    if df:
                        _wcn_click_pref(df, WCN_PREF)
                raw = _shot_viewport(page)
                img = _add_label_banner(raw, lbl)
                fname = f"{fname_prefix}_{suffix}.png"
                results.append((fname, img))
                print(f"[OK] {fname}  {len(img):,} bytes")
            except Exception as e:
                print(f"[WARN] {fname_prefix}_{suffix} 撮影失敗: {e}")

    # 降雪量は5〜10月はスキップ
    month = _jst_now().month
    bunpu_factors = [(s, v) for s, v in WCN_BUNPU_FACTORS
                     if not (s == "snow3h" and 5 <= month <= 10)]
    bunpu_labels  = {"tenki": "天気", "rain3h": "3時間降水量",
                     "snow3h": "3時間降雪量", "temp": "気温"}
    week_labels   = {"tmax": "週間ガイダンス 最高気温",
                     "tmin": "週間ガイダンス 最低気温",
                     "rain": "週間ガイダンス 日降水量"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(
                http_credentials={"username": WCN_USER, "password": WCN_PASS},
                viewport={"width": WCN_VP_W, "height": WCN_VP_H},
            )
            page = ctx.new_page()

            # ── MSM 府県時別 今日 (date=0) ・明日 (date=1) ──────────
            msm_day_labels = {0: "MSM 時別ガイダンス 今日", 1: "MSM 時別ガイダンス 明日"}

            # MSM フォームの選択肢を最初の1回だけ確認
            page.goto(WCN_MSM_URL, wait_until="networkidle", timeout=60_000)
            _ff0 = page.frame(name="form_area")
            if _ff0:
                _fuken_opts = _ff0.locator('select[name="fuken"] option').all()
                print("[DEBUG] fuken options:")
                for _o in _fuken_opts:
                    print(f"  value={_o.get_attribute('value')!r:20s}  text={_o.inner_text()!r}")
                _date_opts = _ff0.locator('select[name="date"] option').all()
                print("[DEBUG] date options:")
                for _o in _date_opts:
                    print(f"  value={_o.get_attribute('value')!r:20s}  text={_o.inner_text()!r}")

            for day_offset, day_lbl in [(0, "d0"), (1, "d1")]:
                try:
                    page.goto(WCN_MSM_URL, wait_until="networkidle", timeout=60_000)
                    ff = page.frame(name="form_area")
                    if not ff:
                        raise RuntimeError("form_area not found")

                    # fuken: label → 失敗したら部分一致
                    fuken_sel = ff.locator('select[name="fuken"]')
                    try:
                        fuken_sel.select_option(label=WCN_PREF)
                    except Exception:
                        opts = fuken_sel.locator("option").all_text_contents()
                        pref_short = WCN_PREF.replace("県", "").replace("府", "").replace("都", "")
                        matched = [o for o in opts if pref_short in o]
                        if matched:
                            fuken_sel.select_option(label=matched[0])
                        else:
                            raise RuntimeError(f"fuken option not found: {WCN_PREF}")

                    # date: index で選択（value が日付文字列のケースに対応）
                    date_sel = ff.locator('select[name="date"]')
                    date_sel.select_option(index=day_offset)

                    with page.expect_event("framenavigated", timeout=15_000):
                        ff.locator('input[type="submit"]').first.click()
                    page.wait_for_timeout(WCN_WAIT_MS)

                    # body 全体撮影 → 横タイルに組み替え
                    raw = _shot_fullbody(page)
                    from PIL import Image as _PILImage
                    import io as _pil_io
                    _tmp = _PILImage.open(_pil_io.BytesIO(raw))
                    # ヘッダーはタイトル行+時刻ラベル行のみ（約60px）
                    # WCN_MSM_HEADER_PX で上書き可能
                    hdr_px = WCN_MSM_HDR_PX if WCN_MSM_HDR_PX > 0 else 60
                    print(f"[INFO] MSM {day_lbl} tile: {WCN_MSM_COLS} cols, header={hdr_px}px, total_h={_tmp.height}px")
                    tiled = _tile_columns(raw, n_cols=WCN_MSM_COLS, header_px=hdr_px)
                    img = _add_label_banner(tiled, msm_day_labels[day_offset])
                    fname = f"wcn_msm_{day_lbl}.png"
                    results.append((fname, img))
                    print(f"[OK] {fname}  {len(img):,} bytes")
                except Exception as e:
                    print(f"[WARN] MSM {day_lbl} 撮影失敗: {e}")

            # ── 分布予報（季節除外済み）──────────────────────────────
            _grab_form_data(page, WCN_BUNPU_URL, "factorNo",
                            bunpu_factors,
                            "wcn_bunpu",
                            [bunpu_labels[s] for s, _ in bunpu_factors],
                            scroll_to_pref=True)

            # ── 週間ガイダンス日データ ────────────────────────────────
            _grab_form_data(page, WCN_WEEK_URL, "factorNo",
                            WCN_WEEK_FACTORS,
                            "wcn_week",
                            [week_labels[s] for s, _ in WCN_WEEK_FACTORS],
                            scroll_to_pref=True)

            # ── 気象庁 秋田県天気予報（公開ページ）────────────────
            try:
                page.goto(JMA_FORECAST_URL, wait_until="networkidle", timeout=60_000)
                # JS レンダリング完了を待つ
                page.wait_for_timeout(4000)
                raw = page.screenshot(full_page=True)
                img = _add_label_banner(raw, "気象庁 秋田県天気予報")
                results.append(("jma_forecast.png", img))
                print(f"[OK] jma_forecast.png  {len(img):,} bytes")
            except Exception as e:
                print(f"[WARN] jma_forecast 撮影失敗: {e}")

            browser.close()
    except Exception as e:
        print(f"[WARN] WCN セッション失敗: {e}")

    return results


# =============================================================================
# 予報データ解析
# =============================================================================


# =============================================================================
# ヘルパー
# =============================================================================


# =============================================================================
# Pillow テーブル描画（amedas.py 共通パターン）
# =============================================================================

def _cell_w(draw, texts: List[str], font, pad: int = 16) -> int:
    max_w = 0
    for t in texts:
        bb = draw.textbbox((0, 0), t, font=font)
        max_w = max(max_w, bb[2] - bb[0])
    return max_w + pad


# =============================================================================
# [1] 市町村天気一覧
# =============================================================================


# =============================================================================
# [2] 短期予報
# =============================================================================


# =============================================================================
# [3] 週間予報
# =============================================================================


# =============================================================================
# R2 アップロード
# =============================================================================

def _upload_r2(items: List[Tuple[str, bytes]]) -> List[str]:
    """(filename, bytes) リストを R2 にアップして URL リストを返す。"""
    if not R2_ENABLE:
        return []
    try:
        from module.utils.r2_utils import put_bytes, make_url
    except ImportError:
        print("[WARN] r2_utils not available")
        return []

    day  = _jst_now().strftime("%Y%m%d")
    urls: List[str] = []
    for fname, data in items:
        key = f"{R2_PREFIX}/{day}/{fname}"
        try:
            put_bytes(key, data, content_type="image/png")
            urls.append(make_url(key))
            print(f"[OK] R2 upload: {key}")
        except Exception as e:
            print(f"[WARN] R2 upload {key}: {e}")
            urls.append("")
    return urls


# =============================================================================
# Notion 書き込み
# =============================================================================


# =============================================================================
# Discord 投稿
# =============================================================================


def _post_images_bulk(images: List[Tuple[str, bytes]], content: str = "") -> None:
    """(filename, bytes) リストを最大10枚ずつ Discord に投稿する。"""
    if not DISCORD_GUIDANCE_WEBHOOK_URL or not images:
        return

    chunk_size = 10
    for chunk_start in range(0, len(images), chunk_size):
        chunk = images[chunk_start: chunk_start + chunk_size]
        boundary = f"----GuidanceBotBulk{chunk_start}"
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
            DISCORD_GUIDANCE_WEBHOOK_URL, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent":   "akita-guidance-bot/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"[OK] Discord bulk HTTP {r.status} ({len(chunk)} files)")
        except Exception as e:
            print(f"[ERR] Discord bulk post: {e}")


# =============================================================================
# MSM R2 投稿ヘルパー
# =============================================================================

def _make_thumbnail(img_bytes: bytes, max_width: int = 1200) -> bytes:
    """Discord 確認用サムネイル（JPEG）を生成する。"""
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(img_bytes)).convert("RGB")
        if img.width > max_width:
            new_h = max(1, int(img.height * (max_width / img.width)))
            img = img.resize((max_width, new_h), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=84, optimize=True, progressive=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] thumbnail 生成失敗: {e}")
        return img_bytes


def _post_msm_r2(img_bytes: bytes, thumb_name: str, content: str) -> None:
    """MSM サムネイルを Discord に添付し、本文に R2 URL を記載する。
    flags=4 (SUPPRESS_EMBEDS) で URL の自動プレビューを抑制し、
    添付サムネイルだけをインライン表示する。
    """
    if not DISCORD_GUIDANCE_WEBHOOK_URL:
        return
    thumb = _make_thumbnail(img_bytes)
    boundary = "----GuidanceMSMR2Thumb"
    payload = {
        "content": content,
        "flags": 4,  # SUPPRESS_EMBEDS: URL プレビュー抑制、添付画像は表示
        "attachments": [{"id": 0, "filename": thumb_name}],
    }
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n"
    ).encode() + json.dumps(payload).encode() + b"\r\n"
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files[0]"; filename="{thumb_name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + thumb + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        DISCORD_GUIDANCE_WEBHOOK_URL, data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "akita-guidance-bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"[OK] Discord MSM R2 thumb HTTP {r.status} ({thumb_name})")
    except Exception as e:
        print(f"[ERR] Discord MSM R2 thumb: {e}")


# =============================================================================
# main
# =============================================================================

def main():
    print("=== Start Guidance (WCN Screenshot) ===")

    wcn_images = screenshot_wcn_all()
    if not wcn_images:
        print("[INFO] WCN スクリーンショットなし（スキップ）")
        print("=== Done ===")
        return

    retention = os.environ.get("R2_RETENTION_DAYS", "21")

    # MSM（今日・明日）: R2 アップ → サムネイル + URL を Discord に投稿
    msm_images  = [(fn, data) for fn, data in wcn_images if fn.startswith("wcn_msm_")]
    other_images = [(fn, data) for fn, data in wcn_images if not fn.startswith("wcn_msm_")]

    if msm_images:
        msm_urls = _upload_r2(msm_images)
        for (fname, data), url in zip(msm_images, msm_urls):
            day_label = "今日" if "d0" in fname else "明日"
            if url:
                content = (
                    f"**MSM 時別ガイダンス {day_label}（秋田県全地点）**\n"
                    f"📥 [高解像度PNGをダウンロード（{retention}日間有効）](<{url}>)"
                )
                thumb_name = fname.replace(".png", "_thumb.jpg")
                _post_msm_r2(data, thumb_name, content)
            else:
                # R2 失敗時はそのまま Discord に直接投稿
                _post_images_bulk([(fname, data)], content=f"**MSM 時別ガイダンス {day_label}**")

    # 分布予報・週間ガイダンス・JMA予報: 直接 Discord 投稿
    if other_images:
        _post_images_bulk(other_images, content="**WCN ガイダンス（分布予報・週間・気象庁予報）**")

    print("=== Done ===")


if __name__ == "__main__":
    main()
