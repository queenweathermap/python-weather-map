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
from module.utils.sns_utils import post_bluesky, post_threads, post_x
from scripts.emagram_discord import (
    STATIONS as EMAGRAM_STATIONS,
    append_caption_bar,
    build_grid_image,
    fetch_image_with_fallback,
    make_thumbnail as make_emagram_thumbnail,
    target_sounding_time,
)

R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")


def upload_r2(key: str, blob: bytes) -> str:
    """climate_3yr.upload_r2 と同等だが、pandas依存のclimate_3yrを
    importせずに済むようここに直接持つ（このジョブはpandasを使わない）。"""
    if not R2_ENABLE:
        return ""
    try:
        from module.utils.r2_utils import put_bytes, make_url
        put_bytes(key, blob, content_type="image/png")
        url = make_url(key)
        print(f"[OK] R2: {url}")
        return url
    except Exception as e:
        print(f"[WARN] R2 upload failed: {e}")
        return ""


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
        # 3枚それぞれを個別に保護する。どれか1つが例外で落ちても、
        # 残りが作れていればその分だけで投稿する（月次・無人実行のため）。
        images = []

        try:
            layout4_images, layout4_errors = build_layout4_only()
            if layout4_errors:
                print(f"[WARN] layout4 errors: {layout4_errors}")
            thumb = _weather_map_thumbnail("04_LAYOUT_4_WEEKLY") if layout4_images else None
            if thumb:
                images.append((thumb, "週間天気 4列結合（週間予報解説・予想天気図3枚）"))
        except Exception as e:
            print(f"[ERR] layout4 build failed: {e}")

        try:
            dashboard_images, dashboard_errors = build_dashboard_jma_only()
            if dashboard_errors:
                print(f"[WARN] dashboard errors: {dashboard_errors}")
            thumb = _weather_map_thumbnail("07_DASHBOARD_JMA_DIRECT") if dashboard_images else None
            if thumb:
                images.append((thumb, "気象庁 全部入りダッシュボード（実況・予想天気図＋高層天気図など）"))
        except Exception as e:
            print(f"[ERR] dashboard build failed: {e}")

        try:
            images.append((_build_emagram_thumbnail(), "高層観測 エマグラム（稚内〜父島の全国15地点）"))
        except Exception as e:
            print(f"[ERR] emagram build failed: {e}")

        if not images:
            print("[ERR] 画像が1枚も作れませんでした")
            return

        caption = (
            "🌏 wx-chart premium\n"
            "　毎日配信中（9月末まで無料）\n"
            "\n"
            "①週間天気（週間予報解説＋予想天気図3枚）\n"
            "②気象庁 全部入りダッシュボード（実況・予想天気図＋高層天気図など）\n"
            "③高層観測エマグラム（全国15地点）\n"
            "詳しくは http://wx-chart.com へ\n"
            "\n"
            "画像はサンプルです\n"
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
