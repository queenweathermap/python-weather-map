# scripts/main_weather_batch.py
# ===============================================
# 毎日定時：GSM/MSM/秋田局地 天気図画像を自動生成＆Slack通知バッチ
# - サブスクリプトで画像生成（*.py）を順次実行
# - 全画像をSlack指定チャンネルに一斉送信（新API v2対応）
# - 画像が無い場合はNO DATA画像を送信
# - モジュール化＆今後の拡張にも対応
# ===============================================

import subprocess
import os
from slack_sdk import WebClient

# ========== 設定 ==========
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")     # GitHub Actions/ローカル共通
SLACK_CHANNEL   = "C08988S0SRY"                        # チャンネルID（"#"は不要・文字列型）

IMG_GSM   = "gsm.png"
IMG_MSM   = "msm.png"
IMG_AKITA = "akita.png"

# ========== 1. 画像生成スクリプト実行 ==========
# 画像生成スクリプト（必要に応じて追加・順序変更もOK）
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

# ========== 2. Slackに画像一斉通知 ==========
def send_weather_images_to_slack(img_paths, channel, slack_token, comment="本日の自動天気図"):
    """画像ファイル群をSlackに一斉通知する（files_upload_v2使用）"""
    client = WebClient(token=slack_token)
    files = []
    for path, title in img_paths:
        if os.path.exists(path):
            files.append({"file": open(path, "rb"), "title": title})
        else:
            print(f"[WARN] 画像が見つかりません: {path}")
    if not files:
        print("[ERROR] 送信する画像がありません。Slack送信スキップ。")
        return
    try:
        client.files_upload_v2(
            channels=channel,
            initial_comment=comment,
            files=files
        )
        print("[OK] Slack通知完了")
    except Exception as e:
        print("Slack送信失敗:", e)

# ========== 3. 送信実行 ==========
send_weather_images_to_slack(
    img_paths=[
        (IMG_GSM,   "GSM 日本域"),
        (IMG_MSM,   "MSM 日本域"),
        (IMG_AKITA, "MSM 秋田局地"),
    ],
    channel=SLACK_CHANNEL,
    slack_token=SLACK_BOT_TOKEN,
    comment="本日の自動天気図（GSM/MSM/秋田局地）"
)

# ========== 4. 不要な画像ファイルを削除（任意）==========
for f in [IMG_GSM, IMG_MSM, IMG_AKITA]:
    try:
        if os.path.exists(f):
            os.remove(f)
            print(f"[CLEAN] 削除: {f}")
    except Exception as e:
        print(f"[WARN] ファイル削除失敗: {f}", e)

print("==== 正常終了 ====")
