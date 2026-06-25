# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_amedas.py
#
# 処理順:
#   1. JMA アメダス 3地点データ取得・R2
#   2. WCN アメダス観測値・ランキング スクリーンショット → Discord
#   3. 全画像を Notion に1件書き込み
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

from module.jobs.amedas import (
    main,
    main_wcn,
    _notion_write,
    JST,
)


if __name__ == "__main__":
    jst_now = datetime.now(JST)

    # JMA データ取得・R2（Notion・Discord は後回し）
    detail_imgs, detail_r2_urls = main(post_discord=False, post_notion=False)

    # WCN スクリーンショット → Discord（アメダスリンク付き）・R2（Notion は後回し）
    wcn_imgs, wcn_r2_urls = main_wcn(post_notion=False)

    # 全 R2 URL をまとめて Notion に1件書き込み
    all_r2_urls = wcn_r2_urls + detail_r2_urls
    ts_str = jst_now.strftime("%m/%d %H:%M")
    _notion_write(
        title=f"AMeDAS 秋田 / {ts_str}",
        r2_urls=all_r2_urls,
        jst_now=jst_now,
    )
