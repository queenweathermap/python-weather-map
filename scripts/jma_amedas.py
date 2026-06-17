# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_amedas.py
#
# ランナー: JMA アメダス描画 + WCN アメダス観測値・ランキング スクリーンショット
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.amedas import main, screenshot_wcn_amedas_pages, post_wcn_amedas_to_discord


if __name__ == "__main__":
    # JMA 公開API による秋田県アメダス描画・Discord 投稿
    main()

    # WCN アメダス観測値・ランキング スクリーンショット・Discord 投稿
    images = screenshot_wcn_amedas_pages()
    if images:
        post_wcn_amedas_to_discord(images)
    else:
        print("[INFO] WCN アメダス画像なし — スキップ")
