# scripts/main_weather_batch.py
# ========================================================
# GSM日本域 天気図パネル生成 → Google Driveアップロード → Slack通知
# コア部分はmodule/core/plotに集約
# 2025-06-27 by ChatGPT
# ========================================================

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from module.utils.drive_utils import upload_to_drive
from module.utils.slack_utils import send_slack_message

# .env ロード
load_dotenv()
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

# パネル画像出力名
init_time = datetime.now().strftime("%Y%m%d_%H%M")
IMG_GSM = f"gsm_panel_{init_time}.jpg"

# 1. 天気図パネル自動生成
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_and_notify

generate_japan_panel_and_notify(
    ymd=datetime.now().strftime("%Y%m%d"),
    hh=datetime.now().strftime("%H"),
    model="GSM",         # or "HYBRID" など運用に合わせて
    output_dir="./data",
    drive_folder="DRIVE_FOLDER_ID",
    ncols=8,
    npages=2,
    only_make=True,      # 通知やDrive処理は下で行う
    out_file=IMG_GSM,
)

# 2. Google Driveアップロード
url = upload_to_drive(os.path.join("./data", IMG_GSM))

# 3. Slack通知
message = f"GSM日本域天気図をアップロードしました：\n{url}"
send_slack_message(message, channel=SLACK_CHANNEL_ID)

print("[OK] 天気図パネル出力・Driveアップ・Slack通知まで正常終了")
