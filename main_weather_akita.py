# main_weather_akita.py
# ========================================================
# 秋田局地パネル出力 → Driveアップロード → Slack通知
# GSM運用、将来MSMに切替可（gpv_panel_daily_local_akita.py を利用）
# ========================================================

import subprocess
from module.drive_utils import upload_to_drive
from module.slack_utils import send_slack_message

OUTPUT_FILENAME = "akita_local_msm_map.jpg"

def main():
    try:
        # 秋田専用パネル生成
        subprocess.run(["python3", "gpv_panel_daily_local_akita.py", OUTPUT_FILENAME], check=True)

        # Driveへアップロード
        url = upload_to_drive(OUTPUT_FILENAME)

        # Slack通知送信（URLのみ）
        send_slack_message(f"秋田局地パネル（自動生成）を更新しました：\n{url}")

    except Exception as e:
        send_slack_message(f"【ERROR】秋田局地パネルの自動処理に失敗しました：{e}")

if __name__ == "__main__":
    main()
