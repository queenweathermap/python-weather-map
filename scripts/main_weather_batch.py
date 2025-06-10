# scripts/main_weather_batch.py
# ===============================================
# 毎日定時：GSM/MSM/秋田局地 天気図画像を自動生成＆Slack通知バッチ
# ===============================================

import subprocess
import os
from module.slack_utils import upload_file_external_slack

# ========== 設定 ==========
SLACK_CHANNEL   = "C08988S0SRY" 

IMG_GSM   = "gsm_weather_map.jpg"
IMG_MSM   = "msm_weather_map.jpg"
IMG_AKITA = "akita_local_msm_map.jpg"

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
for img_path, title in [
    (IMG_GSM, "GSM 日本域"),
    (IMG_MSM, "MSM 日本域"),
    (IMG_AKITA, "MSM 秋田局地"),
]:
    if os.path.exists(img_path):
        upload_file_external_slack(
            channel=SLACK_CHANNEL,
            filepath=img_path,
            title=title,
            initial_comment="本日の自動天気図（GSM/MSM/秋田局地）"
        )
    else:
        print(f"[WARN] 画像が見つかりません: {img_path}（スキップします）")

# ========== 3. 不要な画像ファイルを削除（任意）==========
for f in [IMG_GSM, IMG_MSM, IMG_AKITA]:
    try:
        if os.path.exists(f):
            os.remove(f)
            print(f"[CLEAN] 削除: {f}")
    except Exception as e:
        print(f"[WARN] ファイル削除失敗: {f}", e)

print("==== 正常終了 ====")
