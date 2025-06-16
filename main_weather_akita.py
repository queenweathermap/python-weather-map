# main_weather_akita.py
# ========================================================
# 秋田局地パネル自動生成・共有・通知メインスクリプト（GSM運用）
# --------------------------------------------------------
# 1. gpv_panel_daily_local_akita.py で秋田局地パネル画像を生成
# 2. Google Driveへアップロード（共有リンク自動取得）
# 3. Slackへ画像＋Driveリンクを自動通知
# --------------------------------------------------------
# ・将来MSMにも簡単に切替可（コア部分の構造は変更不要）
# ・CI/CD・定時自動化・Slack速報通知向けテンプレート
# 2025-06-17 by ChatGPT
# ========================================================

import os
import subprocess
from module.utils.slack_utils import upload_file_slack
from module.utils.drive_utils import upload_to_drive

OUTPUT_FILENAME = "akita_local_msm_map.jpg"

def main():
    try:
        # 1. 秋田局地パネル画像を生成（サブスクリプト経由）
        subprocess.run(
            ["python3", "gpv_panel_daily_local_akita.py", OUTPUT_FILENAME],
            check=True
        )

        # 2. Google Driveへアップロードし共有URLを取得
        url = upload_to_drive(OUTPUT_FILENAME)

        # 3. Slackに画像と共有URLを投稿（ファイルアップロード型通知）
        channel = os.environ["SLACK_CHANNEL_ID"]
        upload_file_slack(
            channel=channel,
            filepath=OUTPUT_FILENAME,
            title="Akita Weather Map",
            initial_comment=f"Akita Weather Map\nGoogle Drive URL: {url}"
        )

    except Exception as e:
        # エラー時はprint＋raise（Slack text送信も可：send_slack_text利用）
        print(f"[ERROR] {e}")
        raise

if __name__ == "__main__":
    main()
