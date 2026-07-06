# -*- coding: utf-8 -*-
# =============================================================================
# scripts/daylength.py
#
# 秋田県 昼の長さ / 日の出・日の入り インフォグラフィック
#   本体: module/jobs/daylength.py
#   climate_3yr と同じチャンネル・同じタイミングで投稿する。
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.daylength import main


if __name__ == "__main__":
    main()
