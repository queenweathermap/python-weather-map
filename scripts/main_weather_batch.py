# scripts/main_weather_batch.py
# ========================================================
# GSM日本域 天気図パネル生成 → Google Driveアップロード → Slack通知
# コア部分はmodule/core/plotに集約
# 2025-06-27 by ChatGPT
# ========================================================

# GSM/MSM天気図パネル → Drive → Slack 一発スクリプト
import os
from datetime import datetime
from dotenv import load_dotenv

from module.utils.drive_utils import upload_to_drive
from module.utils.slack_utils import send_slack_message
from module.plotter.gpv_plotter_hybrid import generate_japan_panel_and_notify


# --- .env自動読込 ---
load_dotenv()

# --- 出力パラメータ ---
today = datetime.now().strftime("%Y%m%d")
hour  = datetime.now().strftime("%H")
out_file = f"gsm_panel_{today}_{hour}.jpg"

# --- パネル生成 ---
generate_japan_panel_and_notify(
    ymd=today,
    hh=hour,
    model="HYBRID",            # "GSM"でもOK
    output_dir="./data",
    drive_folder=os.environ.get("DRIVE_FOLDER_ID"),
    ncols=8,
    npages=2,
    only_make=True,            # パネル生成のみ
    out_file=out_file,
)

# --- Google Driveアップロード ---
drive_url = upload_to_drive(os.path.join("./data", out_file))

# --- Slack通知 ---
message = f"【自動配信】GSM/MSM天気図（全国パネル）\n{drive_url}"
send_slack_message(message)

print("[OK] 全処理正常終了")
