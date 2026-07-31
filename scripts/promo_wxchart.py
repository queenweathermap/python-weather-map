# -*- coding: utf-8 -*-
# =============================================================================
# scripts/promo_wxchart.py
#
# wx-chart 宣伝投稿（本番エントリ・月次）
#   週間4列結合＋気象庁全部入りダッシュボード＋高層観測エマグラムの3枚を
#   Bluesky/X/Threads へ 1投稿3枚 で配信。
#   本体: module/jobs/promo_wxchart.py
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.promo_wxchart import main


if __name__ == "__main__":
    main()
