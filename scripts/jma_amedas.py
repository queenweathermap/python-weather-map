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

from module.jobs.amedas import (
    main,
    main_wcn,
    _post_image,
    JMA_AMEDAS_URL,
)


if __name__ == "__main__":
    # JMA データ取得・R2・Notion（Discord 投稿は後回し）
    detail_imgs = main(post_discord=False)

    # WCN スクリーンショット → Discord → Notion
    main_wcn()

    # JMA 3地点詳細を WCN の後に Discord 投稿
    for i, (fname, img_d) in enumerate(detail_imgs):
        content = f"[秋田アメダスマップ](<{JMA_AMEDAS_URL}>)" if i == 0 else ""
        _post_image(img_d, fname, content=content)
