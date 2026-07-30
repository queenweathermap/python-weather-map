# -*- coding: utf-8 -*-
# =============================================================================
# scripts/climate_fukuoka.py
#
# 福岡気象まとめ投稿（本番エントリ）
#   昼の長さ＋過去3年気温(八幡/福岡/久留米)の2枚を、Bluesky/X/Threads へ 1投稿2枚 で配信。
#   本体: module/jobs/climate_city.py
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.climate_city import main


if __name__ == "__main__":
    main("fukuoka")
