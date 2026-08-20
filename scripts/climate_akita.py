# -*- coding: utf-8 -*-
# =============================================================================
# scripts/climate_akita.py
#
# 秋田・気象まとめ投稿（本番エントリ）
#   昼の長さ＋過去3年気温の2枚を、Discord/Bluesky/Threads/Instagram へ 1投稿2枚 で配信。
#   本体: module/jobs/climate_akita.py
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.climate_akita import main


if __name__ == "__main__":
    main()
