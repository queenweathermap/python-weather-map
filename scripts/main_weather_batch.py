import subprocess
import os
import glob
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ========== 設定 ==========
SLACK_TOKEN = os.environ["SLACK_TOKEN"]   # GitHub ActionsのSecretから供給
SLACK_CHANNEL = "#your-channel"           # チャンネルIDまたは名称
WORKDIR = "/workspace"                    # Docker内絶対パス
IMG_GSM = "gsm.png"
IMG_MSM = "msm.png"
IMG_AKITA = "akita.png"

# ========== 1. 各天気図スクリプトを実行 ==========
subprocess.run(["python3", "scripts/gpv_panel_daily_gsm.py", IMG_GSM], check=True)
subprocess.run(["python3", "scripts/gpv_panel_daily_msm.py", IMG_MSM], check=True)
subprocess.run(["python3", "scripts/gpv_panel_daily_msm_akita.py", IMG_AKITA], check=True)

# ========== 2. Slackにまとめて投稿 ==========
client = WebClient(token=SLACK_TOKEN)
try:
    response = client.files_upload_v2(
        channels=SLACK_CHANNEL,
        initial_comment="本日の自動天気図（GSM/日本域・MSM/日本域・MSM/秋田市）",
        files=[
            {"file": open(IMG_GSM, "rb"), "title": "GSM 日本域"},
            {"file": open(IMG_MSM, "rb"), "title": "MSM 日本域"},
            {"file": open(IMG_AKITA, "rb"), "title": "MSM 秋田市"}
        ]
    )
except SlackApiError as e:
    print(f"Slack upload error: {e}")

# ========== 3. 画像ファイル削除 ==========
for f in [IMG_GSM, IMG_MSM, IMG_AKITA]:
    if os.path.exists(f):
        os.remove(f)
