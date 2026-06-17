# -*- coding: utf-8 -*-
# =============================================================================
# scripts/wcn_amedas.py
#
# WCN アメダス観測値・ランキングをスクリーンショットして
# Discord #amedas チャンネルへ投稿する。
# run_jma_amedas.yml から呼び出される。
# =============================================================================

import os
import sys

# リポジトリ直下を import パスに通す（module パッケージを解決するため）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.guidance import screenshot_wcn_amedas_pages, post_wcn_amedas_to_discord


def main():
    images = screenshot_wcn_amedas_pages()
    if images:
        post_wcn_amedas_to_discord(images=images)
    else:
        print("[INFO] 画像なし — Discord 投稿をスキップ")


if __name__ == "__main__":
    main()
