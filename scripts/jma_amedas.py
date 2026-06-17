# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_amedas.py
#
# ランナー: JMA アメダス描画 + WCN アメダス観測値・ランキング スクリーンショット
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.amedas import main, main_wcn


if __name__ == "__main__":
    # JMA 公開API による秋田県アメダス描画 → R2 → Discord → Notion
    main()

    # WCN アメダス観測値・ランキング スクリーンショット → R2 → Discord → Notion
    main_wcn()
