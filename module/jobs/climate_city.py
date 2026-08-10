# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/climate_city.py
#
# 札幌(北海道)・東京・福岡・仙台(宮城)・大阪・沖縄 個別投稿ジョブ
#   ・各都市ごとに「昼の長さ(日の出/日の入り)」と「過去3年の気温比較(代表3地点)」の
#     2枚を生成し、WordPress(wx-chart.com)に本文記事として投稿する（6都市とも）。
#   ・SNS(Bluesky/X/Threads/Instagram)投稿は東京のみ1本にまとめる。
#     昼の長さ＋気温グラフの2枚＋固定のブログ紹介ページ(https://wx-chart.com/note)への
#     リンクを投稿し、他5都市（札幌・福岡・仙台・大阪・沖縄）はブログで公開した旨だけを
#     文中で紹介する（個別のSNS投稿はしない）。
#   ・秋田(climate_akita.py)と同じ枠組み（climate_3yr / daylength の build_figure を再利用）。
#   ・Discordへは投稿しない（秋田専用チャンネルのため、他都市は対象外）。
#   ・代表3地点は「北の地点／県庁所在地・気象官署／南の地点」の秋田パターンに倣う。
# =============================================================================

from __future__ import annotations

from astral import LocationInfo

from module.jobs.climate_3yr import (
    resolve_window,
    is_post_day,
    now_jst,
    upload_r2,
    collect_data,
    build_figure as build_climate_figure,
    elements_for_month,
)
from module.jobs.daylength import build_figure as build_daylength_figure
from module.utils.sns_utils import post_bluesky, post_x, post_threads, post_instagram
from module.utils.wordpress_utils import post_climate_article

CITY_CONFIGS = {
    "sapporo": dict(
        label="北海道（札幌）",
        short="札幌",
        lat=43.0642, lon=141.3469,
        highlight_pref="北海道",
        stations=[
            ("稚内", "11", "47401", "s1"),
            ("札幌", "14", "47412", "s1"),
            ("函館", "23", "47430", "s1"),
        ],
        tags="#北海道 #札幌 #気象 #気温 #日の出 #日の入り",
    ),
    "tokyo": dict(
        label="東京都",
        short="東京",
        lat=35.6812, lon=139.7671,
        highlight_pref="東京都",
        stations=[
            ("八王子", "44", "0366", "a1"),
            ("東京", "44", "47662", "s1"),
            ("大島", "44", "47675", "s1"),
        ],
        tags="#東京 #気象 #気温 #日の出 #日の入り",
    ),
    "fukuoka": dict(
        label="福岡県",
        short="福岡",
        lat=33.5904, lon=130.4017,
        highlight_pref="福岡県",
        stations=[
            ("八幡", "82", "0780", "a1"),
            ("福岡", "82", "47807", "s1"),
            ("久留米", "82", "0790", "a1"),
        ],
        tags="#福岡 #気象 #気温 #日の出 #日の入り",
    ),
    "sendai": dict(
        label="宮城県（仙台）",
        short="仙台",
        lat=38.2682, lon=140.8694,
        highlight_pref="宮城県",
        stations=[
            ("気仙沼", "34", "0242", "a1"),
            ("仙台", "34", "47590", "s1"),
            ("白石", "34", "0256", "a1"),
        ],
        tags="#宮城 #仙台 #気象 #気温 #日の出 #日の入り",
    ),
    "osaka": dict(
        label="大阪府",
        short="大阪",
        lat=34.6937, lon=135.5023,
        highlight_pref="大阪府",
        stations=[
            ("豊中", "62", "0602", "a1"),
            ("大阪", "62", "47772", "s1"),
            ("熊取", "62", "0606", "a1"),
        ],
        tags="#大阪 #気象 #気温 #日の出 #日の入り",
    ),
    "okinawa": dict(
        label="沖縄県",
        short="沖縄",
        lat=26.2124, lon=127.6809,
        highlight_pref="沖縄県",
        # 本州〜九州が収まる既定の地図範囲(128-146E/30-46N)に沖縄県は入らないため、
        # 沖縄本島〜八重山諸島が収まる範囲を明示的に指定する。
        map_xlim=(122, 130), map_ylim=(23, 28),
        stations=[
            ("名護", "91", "47940", "s1"),
            ("那覇", "91", "47936", "s1"),
            ("石垣島", "91", "47918", "s1"),
        ],
        tags="#沖縄 #気象 #気温 #日の出 #日の入り",
    ),
}

# SNS(Bluesky/X/Threads/Instagram)は東京の投稿1本にまとめ、他都市はそこで紹介するだけにする。
NOTE_URL = "https://wx-chart.com/note"
SNS_CITY_KEY = "tokyo"


def main(city_key: str) -> None:
    cfg = CITY_CONFIGS[city_key]
    print(f"=== Start Climate City [{city_key}] ===")

    if not is_post_day():
        print(f"[INFO] 投稿日ではないためスキップ（JST {now_jst():%Y-%m-%d %H:%M}）。強制は CLIMATE_FORCE=1")
        print("=== Skip ===")
        return

    year, month, start_day, end_day, comparison_years = resolve_window()
    half = "前半" if start_day == 1 else "後半"
    print(f"[INFO] target={year}-{month:02d} {start_day}〜{end_day} / years={comparison_years}")

    # --- 画像生成（① 昼の長さ  ② 気温） ---
    observer = LocationInfo(cfg["label"], "Japan", "Asia/Tokyo", cfg["lat"], cfg["lon"]).observer
    daylength_png = build_daylength_figure(
        year, month, start_day, end_day,
        city_label=cfg["label"], observer=observer, highlight_pref=cfg["highlight_pref"],
        map_xlim=cfg.get("map_xlim", (128, 146)), map_ylim=cfg.get("map_ylim", (30, 46)),
    )

    data = collect_data(month, comparison_years, stations=cfg["stations"])
    climate_png = build_climate_figure(
        data, year, month, start_day, end_day, comparison_years, stations=cfg["stations"],
    )

    # --- 文言（積雪の有無で気温の語句を切替） ---
    station_names = "・".join(name for name, *_ in cfg["stations"])
    has_snow = any(k == "snow" for k, _ in elements_for_month(month))
    elem_phrase = "最高最低気温・最深積雪" if has_snow else "最高最低気温"
    tags = cfg["tags"] + (" #積雪" if has_snow else "")

    span = f"{month}/{start_day}〜{month}/{end_day}"
    alt_day = f"{cfg['label']} 日の出・日の入り・昼の長さ {span}"
    alt_cli = f"{station_names} 過去3年 {elem_phrase} 比較 {span}"

    # --- WordPress（本文記事: 昼の長さ＋気温の2枚＋説明文。アイキャッチは設定しない） ---
    wp_title = f"{month}月{half}日の出・日の入りと気温の推移（{cfg['label']}）"
    wp_description = f"{cfg['label']}（{station_names}）の日の出・日の入りと、過去3年間の最高・最低気温の推移です。"
    wp_tags = [city_key.capitalize(), "日の出", "日の入", "気温の推移"]
    # タイトルが日本語のみだとWordPressの自動スラッグ生成で数字だけの読みにくいURLに
    # なりやすいため、半角英数字のスラッグを明示的に指定する（例: tokyo-20260801）。
    wp_slug = f"{city_key}-{year}{month:02d}{start_day:02d}"
    post_climate_article(
        wp_title,
        [(daylength_png, "daylength.png"), (climate_png, "climate.png")],
        wp_description,
        tags=wp_tags,
        category_slug=city_key,
        slug=wp_slug,
    )

    # --- SNS（東京のみ1本。他都市は個別投稿せず、東京の投稿内で紹介する）。 ---
    #     Discordは秋田専用のため投稿しない。
    if city_key != SNS_CITY_KEY:
        print(f"[INFO] SNS投稿はスキップ（{SNS_CITY_KEY}のみ投稿するため）")
        print("=== Done ===")
        return

    other_cities = "・".join(f"#{c['short']}" for k, c in CITY_CONFIGS.items() if k != SNS_CITY_KEY)
    caption = (
        f"｟{month}月{half}｠\n"
        f"{cfg['label']} 昼の長さ（日の出・日の入り）と過去3年の{elem_phrase}をブログに更新しました\n"
        f"{other_cities} はブログで公開\n"
        f"▶ もっとみる: {NOTE_URL}\n"
        f"{tags}"
    )
    images = [(daylength_png, alt_day), (climate_png, alt_cli)]

    post_bluesky(text=caption, images=images)
    post_x(text=caption, images=images)
    post_threads(text=caption, images=images, r2_upload=upload_r2)
    post_instagram(text=caption, images=images, r2_upload=upload_r2)

    print("=== Done ===")
