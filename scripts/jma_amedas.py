# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_amedas.py
#
# 投稿順:
#   1. WCN アメダス観測値・ランキング スクリーンショット
#   2. JMA アメダス 鷹巣・秋田・横手 24時間詳細
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta

from module.jobs.amedas import (
    main,
    main_wcn,
    _post_image,
    _notion_write,
    JMA_AMEDAS_URL,
    JST,
)


if __name__ == "__main__":
    jst_now = datetime.now(JST)

    # JMA データ取得・R2（Notion・Discord は後回し）
    detail_imgs, detail_r2_urls = main(post_discord=False, post_notion=False)

    # WCN スクリーンショット → Discord（Notion は後回し）
    wcn_imgs, wcn_r2_urls = main_wcn(post_notion=False)

    # 全 R2 URL をまとめて Notion に1件書き込み
    all_r2_urls = wcn_r2_urls + detail_r2_urls
    ts_str = jst_now.strftime("%m/%d %H:%M")
    _notion_write(
        title=f"AMeDAS 秋田 / {ts_str}",
        r2_urls=all_r2_urls,
        jst_now=jst_now,
    )

    # JMA 3地点詳細を WCN の後に Discord 投稿
    for i, (fname, img_d) in enumerate(detail_imgs):
        content = f"[秋田アメダスマップ](<{JMA_AMEDAS_URL}>)" if i == 0 else ""
        _post_image(img_d, fname, content=content)
