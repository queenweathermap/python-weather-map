# -*- coding: utf-8 -*-
# =============================================================================
# scripts/climate_sendai.py
#
# 宮城(仙台)気象まとめ投稿（本番エントリ）
#   昼の長さ＋過去3年気温(気仙沼/仙台/白石)の2枚をWordPressに記事投稿し、
#   Bluesky/X/Threads/Instagramへはブログ誘導型で配信する。
#   本体: module/jobs/climate_city.py
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.climate_city import main


if __name__ == "__main__":
    main("sendai")
