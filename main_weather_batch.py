import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from module.utils.drive_utils import upload_to_drive
import requests

# 環境変数の読み込み（ローカル開発用）
load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

# 今日の日付でファイル名を生成
init_time = datetime.now().strftime("%Y%m%d_%H%M")
IMG_GSM   = f"gsm_{init_time}.jpg"
IMG_AKITA = f"akita_{init_time}.jpg"

image_jobs = [
    ("gpv_panel_daily_gsm.py",      IMG_GSM,   "GSM 日本域"),
    ("gpv_panel_daily_msm_akita.py", IMG_AKITA, "GSM 秋田局地"),
]

for script, out_file, label in image_jobs:
    print(f"=== {script} 開始 ===")
    try:
        # 画像生成スクリプト実行
        result = subprocess.run(["python3", script, out_file], check=True, capture_output=True, text=True)
        print(f"[INFO] {script} 実行完了：\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {script} 実行失敗:", e)
        continue

    # ファイルが存在したらDriveアップ＆Slack通知
    if os.path.exists(out_file):
        try:
            url = upload_to_drive(out_file)
            message = f"{label}天気図をGoogle Driveにアップロードしました:\n{url}"
            res = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={
                    "channel": SLACK_CHANNEL_ID,
                    "text": message
                }
            )
            print(f"[INFO] Slack通知: {res.text}")
        except Exception as e:
            print(f"[ERROR] Drive/Slack送信失敗: {e}")
        os.remove(out_file)
    else:
        print(f"[ERROR] 画像が見つかりません: {out_file}")


    if is_no_data_image(filename):
        slack_message = "【注意】本日分の天気図データが取得できませんでした（NO DATA画像です）"
    else:
        slack_message = f"ファイルをGoogle Driveにアップロードしました:\n{drive_url}"


print("==== 正常終了 ====")
