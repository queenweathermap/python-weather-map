# scripts/main_weather_batch.py
# ===============================================
# 毎日定時：GSM/MSM/秋田局地 天気図画像を自動生成＆Slack通知バッチ
# ===============================================

import subprocess
import os
from slack_sdk import WebClient

# ========== 設定 ==========
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")     # GitHub Actions/ローカル共通
SLACK_CHANNEL   = "C08988S0SRY" 

IMG_GSM   = "gsm.png"
IMG_MSM   = "msm.png"
IMG_AKITA = "akita.png"

# ========== 1. 画像生成スクリプト実行 ==========
image_jobs = [
    ("scripts/gpv_panel_daily_gsm.py",   IMG_GSM),
    ("scripts/gpv_panel_daily_msm.py",   IMG_MSM),
    ("scripts/gpv_panel_daily_msm_akita.py", IMG_AKITA),
]

for script, out_file in image_jobs:
    try:
        subprocess.run(["python3", script, out_file], check=True)
    except Exception as e:
        print(f"[ERROR] {script} 実行失敗:", e)

# ========== 2. Slackに画像を順送りで投稿 ==========
def send_multiple_files_to_slack(file_title_list, channel, slack_token, initial_comment="本日の天気図です！"):
    client = WebClient(token=slack_token)
    sent_any = False
    for image_path, title in file_title_list:
        if os.path.exists(image_path):
            try:
                response = client.files_upload(
                    channels=channel,
                    file=image_path,
                    title=title,
                    initial_comment=initial_comment if not sent_any else None
                )
                print(f"[Slack送信] {title}: OK")
                sent_any = True
            except Exception as e:
                print(f"Error: {title} Slack送信失敗:", e)
        else:
            print(f"[WARN] 画像が見つかりません: {image_path}")
    if not sent_any:
        print("[ERROR] 送信する画像がありません。Slack送信スキップ。")

# ========== 3. 送信実行 ==========
for img_path, title in [
    ("gsm.png", "GSM 日本域"),
    ("msm.png", "MSM 日本域"),
    ("akita.png", "MSM 秋田局地")
]:
    if os.path.exists(img_path):
        upload_file_external_slack(
            channel="C08988S0SRY",
            filepath=img_path,
            title=title,
            initial_comment=f"本日の自動天気図（{title}）"
        )
    else:
        print(f"[WARN] 画像が見つかりません: {img_path}")


# ========== 4. 不要な画像ファイルを削除（任意）==========
for f in [IMG_GSM, IMG_MSM, IMG_AKITA]:
    try:
        if os.path.exists(f):
            os.remove(f)
            print(f"[CLEAN] 削除: {f}")
    except Exception as e:
        print(f"[WARN] ファイル削除失敗: {f}", e)

print("==== 正常終了 ====")
