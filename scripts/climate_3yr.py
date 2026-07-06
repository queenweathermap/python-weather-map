# -*- coding: utf-8 -*-
# =============================================================================
# scripts/climate_3yr.py
#
# 過去3年 気象データ比較グラフ（秋田県3地点）→ R2 → Discord 専用チャンネル
#   本体: module/jobs/climate_3yr.py
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.climate_3yr import main


if __name__ == "__main__":
    main()
