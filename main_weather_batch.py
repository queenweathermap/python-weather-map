# main_weather_batch.py
# ========================================================
# GSM日本域の天気図パネルを生成 → Driveアップロード → Slack通知
# --------------------------------------------------------
# ※秋田局地の処理は除外済（2025-06-17）
# ※gpv_panel_daily_gsm.py を使って全国図を作成
# ========================================================

import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from module.utils.drive_utils import upload_to_drive
import requests

# --------------------------------------------------------
# ローカル開発用：.envファイルから環境変数を読み込む
# --------------------------------------------------------
load_dotenv()

# --------------------------------------------------------
# Slack通知とDriveアップロードに必要な環境変数
# --------------------------------------------------------
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

# --------------------------------------------------------
# 実行時刻からファイル名を生成（例：gsm_20250617_0500.jpg）
# --------------------------------------------------------
init_time = datetime.now().strftime("%Y%m%d_%H%M")
IMG_GSM = f"gsm_{init_time}.jpg"

# --------------------------------------------------------
# 出力対象スクリプトとファイル名、通知ラベルの一覧
# --------------------------------------------------------
image_jobs = [
    ("gpv_panel_daily_gsm.py", IMG_GSM, "GSM 日本域")
]

# --------------------------------------------------------
# 各スクリプトを実行 → Driveアップロード → Slack通知
# --------------------------------------------------------
for script, out_file, label in image_jobs:
    print(f"=== {script} 開始 ===")
    try:
        # 天気図生成スクリプトを実行
        result = subprocess.run(
            ["python3", script, out_file],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"[INFO] {script} 実行完了：\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {script} 実行失敗:", e)
        continue

    # 出力ファイルが存在する場合のみアップロード＆通知
    if os.path.exists(out_file):
        try:
            # Google Driveにアップロードし、共有URLを取得
            url = upload_to_drive(out_file)

            # Slackに通知（テキストメッセージのみ）
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
        finally:
            # ローカルの画像ファイルを削除
            os.remove(out_file)
    else:
        print(f"[ERROR] 画像が見つかりません: {out_file}")

print("==== 正常終了 ====")
