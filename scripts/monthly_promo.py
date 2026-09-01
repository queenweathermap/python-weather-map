# -*- coding: utf-8 -*-
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# scripts/monthly_promo.py
# 毎月10日、1日00Zの全部入り天気図をBluesky/Threads/Facebook/Instagramに投稿する。
from module.jobs.monthly_promo import main

if __name__ == "__main__":
    main()
