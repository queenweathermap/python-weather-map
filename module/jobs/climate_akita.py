# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/climate_akita.py
#
# 秋田・気象まとめ投稿（本番エントリ）
#   ・「昼の長さ(日の出/日の入り)」と「過去3年の気温(冬は積雪も)比較」の2枚を生成し、
#     Discord・Bluesky・X・Threads すべてに **1投稿2枚** でまとめて投稿する。
#   ・図の生成は climate_3yr / daylength の build_figure を再利用（重複なし）。
#   ・期間・投稿日ゲート・R2・Discordのwebhookも climate_3yr の関数を再利用。
#
# 画像の並び: ① 昼の長さ  ② 気温(・積雪)   ※キャプションの並びに合わせる
# =============================================================================

from __future__ import annotations

import os

from module.jobs.climate_3yr import (
    resolve_window,
    is_post_day,
    now_jst,
    upload_r2,
    discord_webhook_url,
    collect_data,
    build_figure as build_climate_figure,
    elements_for_month,
)
from module.jobs.daylength import build_figure as build_daylength_figure
from module.utils.sns_utils import post_bluesky, post_x, post_threads, post_instagram, post_discord_images

DISCORD_ENABLE = os.environ.get("DISCORD_ENABLE", "1").lower() in ("1", "true", "yes", "on")


# =============================================================================
# Discord（1メッセージ・複数画像添付）
# =============================================================================
def post_discord_combined(content: str, images, r2_links) -> None:
    """
    images   : [(filename, png_bytes), ...] を1メッセージに添付
    r2_links : [(ラベル, url), ...] を本文に太字リンクで付与
    """
    url = discord_webhook_url()
    if not (DISCORD_ENABLE and url):
        print("[INFO] Discord 無効")
        return
    post_discord_images(webhook_url=url, content=content, images=images, r2_links=r2_links)


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start Climate Akita (combined) ===")

    if not is_post_day():
        print(f"[INFO] 投稿日ではないためスキップ（JST {now_jst():%Y-%m-%d %H:%M}）。強制は CLIMATE_FORCE=1")
        print("=== Skip ===")
        return

    year, month, start_day, end_day, comparison_years = resolve_window()
    half = "前半" if start_day == 1 else "後半"
    print(f"[INFO] target={year}-{month:02d} {start_day}〜{end_day} / years={comparison_years}")

    # --- 画像生成（① 昼の長さ  ② 気温） ---
    daylength_png = build_daylength_figure(year, month, start_day, end_day)
    data = collect_data(month, comparison_years)
    climate_png = build_climate_figure(data, year, month, start_day, end_day, comparison_years)

    # --- キャプション（積雪の有無で気温の語句を切替） ---
    has_snow = any(k == "snow" for k, _ in elements_for_month(month))
    elem_phrase = "最高最低気温・最深積雪" if has_snow else "最高最低気温"
    tags = "#秋田 #気象 #気温 #日の出 #日の入り" + (" #積雪" if has_snow else "")
    caption = (
        f"｟{month}月{half}｠\n"
        f"秋田県 昼の長さ（日の出・日の入り）\n"
        f"秋田・鷹巣・横手 過去3年の{elem_phrase}\n"
        f"{tags}"
    )

    span = f"{month}/{start_day}〜{month}/{end_day}"
    alt_day = f"秋田県 日の出・日の入り・昼の長さ {span}"
    alt_cli = f"秋田3地点 過去3年 {elem_phrase} 比較 {span}"

    # ① 昼の長さ → ② 気温 の順
    images = [(daylength_png, alt_day), (climate_png, alt_cli)]

    # --- R2（Discord高解像度リンク用） ---
    url_day = upload_r2(f"{year}{month:02d}/daylength_{half}_{start_day:02d}-{end_day:02d}.png", daylength_png)
    url_cli = upload_r2(f"{year}{month:02d}/climate_{half}_{start_day:02d}-{end_day:02d}.png", climate_png)

    # --- Discord（1メッセージ・2枚） ---
    post_discord_combined(
        caption,
        [("daylength.png", daylength_png), ("climate.png", climate_png)],
        [("昼の長さ 高解像度", url_day), ("気温 高解像度", url_cli)],
    )

    # --- SNS（各1投稿・2枚） ---
    post_bluesky(text=caption, images=images)
    post_x(text=caption, images=images)
    post_threads(text=caption, images=images, r2_upload=upload_r2)
    post_instagram(text=caption, images=images, r2_upload=upload_r2)

    print("=== Done ===")


if __name__ == "__main__":
    main()
