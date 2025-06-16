# main_weather_akita.py
# ========================================================
# 秋田局地パネル自動生成・共有・通知メインスクリプト（GSM運用）
# --------------------------------------------------------
# 1. gpv_panel_daily_local_akita.py で秋田局地パネル画像を生成
# 2. Google Driveへアップロード（共有リンク自動取得）
# 3. SlackへGoogle DriveのURLだけ通知（ファイル本体はアップしない）
# --------------------------------------------------------
# 2025-06-18 by ChatGPT
# ========================================================

import os
import subprocess
from module.utils.slack_utils import send_slack_text  # ← テキスト通知だけでOK
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

        # 3. SlackにはGoogle Drive URLだけをテキストで通知
        channel = os.environ["SLACK_CHANNEL_ID"]
        msg = f"秋田局地天気図（最新）\nGoogle Drive共有URL: {url}"
        send_slack_text(channel, msg)

    except Exception as e:
        # エラー時はprint＋Slackにエラー内容通知
        print(f"[ERROR] {e}")
        try:
            channel = os.environ.get("SLACK_CHANNEL_ID")
            if channel:
                send_slack_text(channel, f"[ERROR] 秋田局地パネル通知で例外発生: {e}")
        except Exception:
            pass
        raise

if __name__ == "__main__":
    main()
