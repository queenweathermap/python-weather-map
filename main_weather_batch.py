# main_weather_batch.py
# ===============================================
# GSM全国・秋田局地の天気図画像を自動生成しSlackに投稿
# 他通知・アップロード（LINE/Drive/メール）は一切なし
# 2025-06-16 by ChatGPT
# ===============================================

import subprocess
import os
from datetime import datetime
from dotenv import load_dotenv

from module.utils.slack_utils import upload_file_external_slack

# --- .env読込（GitHub Actions上は無視されるがローカル開発用に） ---
load_dotenv()

init_time = datetime.now().strftime("%Y%m%d_%H%M")
DESKTOP_DIR = os.path.expanduser("~/Desktop")

IMG_GSM   = os.path.join(DESKTOP_DIR, f"gsm_{init_time}.jpg")
IMG_AKITA = os.path.join(DESKTOP_DIR, f"akita_{init_time}.jpg")

image_jobs = [
    ("gpv_panel_daily_gsm.py",      IMG_GSM,   "GSM 日本域"),
    ("gpv_panel_daily_msm_akita.py", IMG_AKITA, "GSM 秋田局地"),
]

slack_token = os.environ.get("SLACK_BOT_TOKEN")
slack_channel = os.environ.get("SLACK_CHANNEL_ID")  # 例: "C12345678"

if not slack_token or not slack_channel:
    print("[ERROR] SLACK_BOT_TOKENまたはSLACK_CHANNEL_IDが未設定です")
    exit(1)

for script, out_file, label in image_jobs:
    print(f"=== {script} 開始 ===")
    try:
        result = subprocess.run(["python3", script, out_file], check=True, capture_output=True, text=True)
        print(f"[INFO] {script} 実行完了：\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {script} 実行失敗:")
        print("  コマンド:", e.cmd)
        print("  リターンコード:", e.returncode)
        print("  標準出力:", e.stdout)
        print("  標準エラー:", e.stderr)
        continue
    except Exception as e:
        print(f"[ERROR] {script} 例外:", e)
        continue

    # --- Slack投稿 ---
    if os.path.exists(out_file):
        print(f"[Slack通知] 送信: {out_file}")
        try:
            upload_file_external_slack(
                slack_channel,
                out_file,
                title=f"{label} 天気図",
                initial_comment=f"{label}の天気図を自動配信します"
            )
        except Exception as e:
            print(f"[ERROR] Slack送信失敗: {out_file} {e}")
    else:
        print(f"[ERROR] 画像が見つかりません: {out_file}")

print("==== 正常終了 ====")
