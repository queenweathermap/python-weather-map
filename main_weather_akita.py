# main_weather_akita.py
# ========================================================
# 秋田局地パネル出力 → Driveアップロード → Slack通知
# GSM運用、将来MSMに切替可（gpv_panel_daily_local_akita.py を利用）
# ========================================================

import os
import subprocess
from module.utils.slack_utils import upload_file_slack
from module.utils.drive_utils import upload_to_drive

OUTPUT_FILENAME = "akita_local_msm_map.jpg"

def main():
    try:
        # 1. 秋田局地パネル生成（画像出力）
        subprocess.run(["python3", "gpv_panel_daily_local_akita.py", OUTPUT_FILENAME], check=True)

        # 2. Google Drive にアップロード（共有URL取得）
        url = upload_to_drive(OUTPUT_FILENAME)

        # 3. Slack に画像付きで投稿（ファイルアップロード型）
        channel = os.environ["SLACK_CHANNEL_ID"]
        upload_file_slack(
            channel=channel,
            filepath=OUTPUT_FILENAME,
            title="Akita Weather Map",
            initial_comment=f"Akita Weather Map！\n共有URL: {url}"
        )

    except Exception as e:
        # 失敗時だけテキストで送信したい場合、ここに send_slack_message を定義してもOK
        print(f"ERROR: {e}")
        raise

if __name__ == "__main__":
    main()
