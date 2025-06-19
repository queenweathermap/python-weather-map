# main_weather_batch.py
# ========================================================
# GSM日本域 天気図パネル生成 → Google Driveアップロード → Slack通知
# --------------------------------------------------------
# ・gpv_panel_daily_gsm.pyで全国天気図を自動生成
# ・Drive共有URLをSlackにテキスト通知
# ・ローカル開発用に .env から各種キーを読込
# ・エラー時も最後まで自動運用を継続
# --------------------------------------------------------
# 2025-06-17 by ChatGPT
# ========================================================

import os
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from module.utils.drive_utils import upload_to_drive
import requests

# --------------------------------------------------------
# ローカル開発・本番環境両対応：.envから環境変数ロード
# --------------------------------------------------------
load_dotenv()

# --------------------------------------------------------
# Slack通知やDriveアップロード用の環境変数（.env等で設定必須）
# --------------------------------------------------------
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]

# --------------------------------------------------------
# 出力ファイル名：日付・時刻付き（重複防止・記録性確保）
# 例）gsm_20250617_0500.jpg
# --------------------------------------------------------
init_time = datetime.now().strftime("%Y%m%d_%H%M")
IMG_GSM = f"gsm_{init_time}.jpg"
IMG_MSM = f"msm_{init_time}.jpg"

image_jobs = [
    ("gpv_panel_daily_gsm.py", IMG_GSM, "GSM 日本域"),
    ("gpv_panel_daily_msm.py", IMG_MSM, "MSM 日本域"),
]

# --------------------------------------------------------
# スクリプト・ファイル名・ラベルの定義リスト
# 必要に応じて複数出力も拡張可
# --------------------------------------------------------
image_jobs = [
    ("gpv_panel_daily_gsm.py", IMG_GSM, "GSM 日本域")
]

# --------------------------------------------------------
# 各天気図スクリプト実行 → Google Driveアップロード → Slack通知
# --------------------------------------------------------
for script, out_file, label in image_jobs:
    print(f"=== {script} 実行開始 ===")
    try:
        result = subprocess.run(
            ["python3", script, out_file],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"[INFO] {script} 実行完了：\n{result.stdout}")
        print(f"[INFO] {script} エラー出力：\n{result.stderr}")

        if os.path.exists(out_file):
            url = upload_to_drive(out_file)
            message = f"{label} 天気図をGoogle Driveにアップロードしました：\n{url}"
            res = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"channel": SLACK_CHANNEL_ID, "text": message}
            )
            print(f"[INFO] Slack通知: {res.text}")
            os.remove(out_file)
        else:
            print(f"[ERROR] 画像が見つかりません: {out_file}")

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {script} 実行失敗: {e}")
        print("stdout:\n", e.stdout)
        print("stderr:\n", e.stderr)
    except Exception as e:
        print(f"[ERROR] Drive/Slack送信失敗: {e}")

print("==== 正常終了 ====")
