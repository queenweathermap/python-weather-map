# -*- coding: utf-8 -*-
# scripts/jma_advisor_guidance.py
# JMA 気象防災アドバイザー ガイダンス帳票 → Discord (ADV専用チャンネル)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.advisor_guidance import main

if __name__ == "__main__":
    main()
