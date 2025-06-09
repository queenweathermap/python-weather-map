# scripts/main_weather_batch.py
import subprocess, os
from slack_sdk import WebClient

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL   = "C08988S0SRY"
IMG_GSM = "gsm.png"
IMG_MSM = "msm.png"
IMG_AKITA = "akita.png"

# 1. 各天気図生成スクリプト
subprocess.run(["python3", "scripts/gpv_panel_daily_gsm.py", IMG_GSM], check=True)
subprocess.run(["python3", "scripts/gpv_panel_daily_msm.py", IMG_MSM], check=True)
subprocess.run(["python3", "scripts/gpv_panel_daily_msm_akita.py", IMG_AKITA], check=True)

# 2. Slackで3枚同時送信
client = WebClient(token=SLACK_BOT_TOKEN)
client.files_upload_v2(
    channels=SLACK_CHANNEL,
    initial_comment="本日の自動天気図（GSM/日本域・MSM/日本域・MSM/秋田市）",
    files=[
        {"file": open(IMG_GSM, "rb"),   "title": "GSM 日本域"},
        {"file": open(IMG_MSM, "rb"),   "title": "MSM 日本域"},
        {"file": open(IMG_AKITA, "rb"), "title": "MSM 秋田市"},
    ]
)
