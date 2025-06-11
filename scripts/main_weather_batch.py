# scripts/main_weather_batch.py
# ===============================================
# 毎日定時：GSM/MSM/秋田局地 天気図画像を自動生成＆Slack通知バッチ
# ===============================================import subprocess

import os
from dotenv import load_dotenv
from module.slack_utils import upload_file_external_slack
from module.mail_utils import send_mail

# --- .envの読み込み
load_dotenv()

SLACK_CHANNEL = os.environ["SLACK_CHANNEL"]
MAIL_TO = os.environ["MAIL_TO"]

IMG_GSM   = "gsm_weather_map.jpg"
IMG_MSM   = "msm_weather_map.jpg"
IMG_AKITA = "akita_local_msm_map.jpg"

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

# 画像通知
for img_path, title in [
    (IMG_GSM, "GSM 日本域"),
    (IMG_MSM, "MSM 日本域"),
    (IMG_AKITA, "MSM 秋田局地"),
]:
    if os.path.exists(img_path):
        # Slack
        upload_file_external_slack(
            channel=SLACK_CHANNEL,
            filepath=img_path,
            title=title,
            initial_comment="本日の自動天気図（GSM/MSM/秋田局地）"
        )
        # メール
        send_mail(
            to=MAIL_TO,
            subject=title,
            body="本日の自動天気図です",
            attachments=[img_path]
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
