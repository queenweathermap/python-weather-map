# main_weather_batch.py
# ===============================================
# 毎日定時：GSM/MSM/秋田局地 天気図画像を自動生成＆LINE通知＆Driveアップロードバッチ
# ===============================================

import subprocess
import os
from datetime import datetime
from dotenv import load_dotenv

# ======= 外部ユーティリティimport（新ディレクトリ構成対応） =======
from module.utils.line_utils import send_line_text
from module.utils.drive_utils import upload_to_drive
# from module.utils.slack_utils import upload_file_external_slack  # Slack通知（必要に応じて）
# from module.utils.mail_utils import send_mail                   # メール通知（必要に応じて）

# --- .envの読み込み（LINE/Drive用トークン等は各ユーティリティ側で取得） ---
load_dotenv()

print("環境変数一覧", dict(os.environ))


# ================================================
# 1. ファイル名（日時付き）・保存場所（iCloud Desktop）を指定
# ================================================
init_time = datetime.now().strftime("%Y%m%d_%H%M")  # 例: 20250613_0500
DESKTOP_DIR = os.path.expanduser("~/Desktop")  # Mac/iCloud連携用

IMG_GSM   = os.path.join(DESKTOP_DIR, f"gsm_{init_time}.jpg")
IMG_MSM   = os.path.join(DESKTOP_DIR, f"msm_{init_time}.jpg")
IMG_AKITA = os.path.join(DESKTOP_DIR, f"akita_{init_time}.jpg")

image_jobs = [
    ("scripts/gpv_panel_daily_gsm.py",      IMG_GSM),
    ("scripts/gpv_panel_daily_msm.py",      IMG_MSM),
    ("scripts/gpv_panel_daily_msm_akita.py", IMG_AKITA),
]

for script, out_file in image_jobs:
    try:
        subprocess.run(["python3", script, out_file], check=True)
    except Exception as e:
        print(f"[ERROR] {script} 実行失敗:", e)

# ================================================
# 2. 画像存在チェックとDrive自動アップロード
# ================================================
images_info = [
    (IMG_GSM,   "GSM 日本域"),
    (IMG_MSM,   "MSM 日本域"),
    (IMG_AKITA, "MSM 秋田局地"),
]

exist_files = [img_path for img_path, _ in images_info if os.path.exists(img_path)]

# Drive共有URL取得リスト
drive_urls = []
for img_path in exist_files:
    try:
        url = upload_to_drive(img_path)
        drive_urls.append((os.path.basename(img_path), url))
    except Exception as e:
        print(f"[ERROR] Driveアップロード失敗: {img_path} {e}")

# ================================================
# 3. LINEテキスト通知（ファイル名とDrive共有URLを記載）
# ================================================
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

# ================================================
# 4. .nc等の一時ファイル削除（必要に応じて追加）
# ================================================
# 画像（jpg）はiCloudやDriveに残しておきます
# もし他に削除したいファイルがあれば、ここで処理

print("==== 正常終了 ====")
