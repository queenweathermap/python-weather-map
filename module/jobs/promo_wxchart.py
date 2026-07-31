# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/promo_wxchart.py
#
# wx-chart 宣伝投稿（月次・毎月10日）
#   ・週間4列結合 / 気象庁 全部入りダッシュボード / 高層観測エマグラム(15地点)
#     の3枚を Bluesky・X・Threads へ 1投稿3枚 でまとめて配信する。
#   ・画像はDiscordで実際に使っているサムネイル生成をそのまま再利用する
#     （make_discord_thumbnail / make_thumbnail）。元画像は非常に大きい
#     （実測: 全部入り 11235x7338 / 週間4列 8809x3767）が、これらの関数が
#     既にSNS向けの軽量JPEGサムネイルに縮小してくれる。
#   ・Discordには投稿しない（各画像は既存の専用チャンネルで既に配信されている）。
# =============================================================================

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

from module.jobs.weather_map import (
    DATA_DIR,
    OUTPUT_DIR,
    build_dashboard_jma_only,
    build_layout4_only,
    jma_source_caption,
    make_discord_thumbnail,
)
from module.jobs.climate_3yr import upload_r2
from module.utils.sns_utils import post_bluesky, post_threads, post_x
from scripts.emagram_discord import (
    STATIONS as EMAGRAM_STATIONS,
    append_caption_bar,
    build_grid_image,
    fetch_image_with_fallback,
    make_thumbnail as make_emagram_thumbnail,
    target_sounding_time,
)


def _weather_map_thumbnail(filename: str) -> bytes | None:
    src_path = os.path.join(OUTPUT_DIR, f"{filename}.png")
    if not os.path.exists(src_path):
        print(f"[WARN] thumbnail source missing: {src_path}")
        return None
    thumb_path, _mime = make_discord_thumbnail(
        src_path, caption_text=jma_source_caption(datetime.now(timezone.utc)),
    )
    with open(thumb_path, "rb") as f:
        return f.read()


def _build_emagram_thumbnail() -> bytes:
    dt = target_sounding_time()
    stations_with_images = [
        (name, fetch_image_with_fallback(stnm, name, dt)) for stnm, name in EMAGRAM_STATIONS
    ]
    combined = build_grid_image(stations_with_images)
    combined = append_caption_bar(combined, dt)
    return make_emagram_thumbnail(combined, dt)


def main() -> None:
    print("=== Start Promo WxChart (monthly) ===")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        layout4_images, layout4_errors = build_layout4_only()
        dashboard_images, dashboard_errors = build_dashboard_jma_only()

        for errs, label in ((layout4_errors, "layout4"), (dashboard_errors, "dashboard")):
            if errs:
                print(f"[WARN] {label} errors: {errs}")

        images = []
        layout4_thumb = _weather_map_thumbnail("04_LAYOUT_4_WEEKLY") if layout4_images else None
        if layout4_thumb:
            images.append((layout4_thumb, "週間天気 4列結合（週間予報解説・予想天気図3枚）"))

        dashboard_thumb = _weather_map_thumbnail("07_DASHBOARD_JMA_DIRECT") if dashboard_images else None
        if dashboard_thumb:
            images.append((dashboard_thumb, "気象庁 全部入りダッシュボード（実況・予想天気図＋高層天気図など）"))

        images.append((_build_emagram_thumbnail(), "高層観測 エマグラム（稚内〜父島の全国15地点）"))

        if not images:
            print("[ERR] 画像が1枚も作れませんでした")
            return

        caption = (
            "🌏 wx-chart 月次まとめ\n"
            "①週間天気（週間予報解説＋予想天気図3枚）\n"
            "②気象庁 全部入りダッシュボード（実況・予想天気図＋高層天気図など）\n"
            "③高層観測エマグラム（全国15地点）\n"
            "を毎日配信中。詳しくは wx-chart.com へ\n"
            "#天気 #気象 #天気図 #WxChart"
        )

        post_bluesky(text=caption, images=images)
        post_x(text=caption, images=images)
        post_threads(text=caption, images=images, r2_upload=upload_r2)

        print("=== Done ===")
    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
