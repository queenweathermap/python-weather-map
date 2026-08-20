# -*- coding: utf-8 -*-
# =============================================================================
# scripts/climate_osaka.py
#
# 大阪気象まとめ投稿（本番エントリ）
#   昼の長さ＋過去3年気温(豊中/大阪/熊取)の2枚をWordPressに記事投稿し、
#   Bluesky/Threads/Instagramへはブログ誘導型で配信する。
#   本体: module/jobs/climate_city.py
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.climate_city import main


if __name__ == "__main__":
    main("osaka")
