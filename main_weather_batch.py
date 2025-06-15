# main_weather_batch.py
# ===============================================
# GSM/MSM/秋田局地 天気図画像を自動生成＋Slack通知＋Drive/LINEアップロードバッチ
# -----------------------------------------------
# ・定時実行で各種天気図を生成、Slack/Drive/LINEに配信
# ・APIキーやTokenは環境変数から取得
# ・どの通知が失敗しても他は続行（ロバスト設計）
# 2025-06-16 by ChatGPT
# ===============================================

import subprocess
import os
from datetime import datetime
from dotenv import load_dotenv

# ---- 各通知ユーティリティ ----
from module.utils.slack_utils import upload_file_external_slack
from module.utils.line_utils import send_line_text
from module.utils.drive_utils import upload_to_drive

# --- 環境変数読込（.env優先・GitHub ActionsでもOK） ---
load_dotenv()
print("【DEBUG】環境変数一覧", dict(os.environ))

init_time = datetime.now().strftime("%Y%m%d_%H%M")
DESKTOP_DIR = os.path.expanduser("~/Desktop")

IMG_GSM   = os.path.join(DESKTOP_DIR, f"gsm_{init_time}.jpg")
IMG_MSM   = os.path.join(DESKTOP_DIR, f"msm_{init_time}.jpg")
IMG_AKITA = os.path.join(DESKTOP_DIR, f"akita_{init_time}.jpg")

image_jobs = [
    ("gpv_panel_daily_gsm.py",      IMG_GSM),
    ("gpv_panel_daily_msm.py",      IMG_MSM),
    ("gpv_panel_daily_msm_akita.py", IMG_AKITA),
]

# --- 1. 画像生成（各スクリプトごと） ---
for script, out_file in image_jobs:
    print(f"=== {script} 開始 ===")
    try:
        result = subprocess.run(["python3", script, out_file], check=True, capture_output=True, text=True)
        print(f"[INFO] {script} 実行完了：標準出力\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {script} 実行失敗:")
        print("  コマンド:", e.cmd)
        print("  リターンコード:", e.returncode)
        print("  標準出力:", e.stdout)
        print("  標準エラー:", e.stderr)
    except Exception as e:
        print(f"[ERROR] {script} その他の例外:", e)

images_info = [
    (IMG_GSM,   "GSM 日本域"),
    (IMG_MSM,   "MSM 日本域"),
    (IMG_AKITA, "MSM 秋田局地"),
]

# --- 2. Slack通知（画像があれば順次送信） ---
slack_token = os.environ.get("SLACK_BOT_TOKEN")
slack_channel = os.environ.get("SLACK_CHANNEL_ID")  # 例: "C12345678"
if slack_token and slack_channel:
    for img_path, label in images_info:
        if os.path.exists(img_path):
            print(f"[Slack通知] 送信: {img_path}")
            try:
                upload_file_external_slack(
                    slack_channel,
                    img_path,
                    title=f"{label} 天気図",
                    initial_comment=f"{label}の天気図を自動配信します"
                )
            except Exception as e:
                print(f"[ERROR] Slack送信失敗: {img_path} {e}")

# --- 3. Google Driveアップロード ---
exist_files = [img_path for img_path, _ in images_info if os.path.exists(img_path)]
drive_urls = []
for img_path in exist_files:
    try:
        url = upload_to_drive(img_path)
        drive_urls.append((os.path.basename(img_path), url))
    except Exception as e:
        print(f"[ERROR] Driveアップロード失敗: {img_path} {e}")

# --- 4. LINE通知（URL or 保存情報を送信） ---
if drive_urls:
    msg = "本日の自動天気図（GSM/MSM/秋田局地）画像を\nGoogle Driveにアップロードしました。\n\n"
    msg += "\n".join(f"- {name}\n{url}" for name, url in drive_urls)
    send_line_text(msg)
elif exist_files:
    filenames = [os.path.basename(f) for f in exist_files]
    msg = "本日の自動天気図（GSM/MSM/秋田局地）画像を\nMac/iPhoneのiCloudデスクトップに保存しました。\n\n"
    msg += "\n".join(f"- {name}" for name in filenames)
    send_line_text(msg)
else:
    send_line_text("本日の天気図画像が生成できませんでした")

print("==== 正常終了 ====")
