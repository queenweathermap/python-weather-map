# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知
# 2025-06-27 ChatGPT 新core設計準拠・最新イニシャル自動判定付き
# ===============================================================

import os
import glob
from io import StringIO 
import datetime

from module.plotter.gpv_plotter_hybrid import generate_japan_panel_and_notify
from module.utils.slack_utils import send_slack_text

def get_latest_gpv_init(now=None):
    """ 実行時点で取得可能なGPVイニシャル時刻（UTC, 3時間毎）を返す """
    if now is None:
        now = datetime.datetime.now()
    now_utc = now - datetime.timedelta(hours=9)  # JST→UTC
    hour = now_utc.hour
    init_hour = max([h for h in range(0, 24, 3) if h <= hour])
    dt_init = now_utc.replace(hour=init_hour, minute=0, second=0, microsecond=0)
    ymd = dt_init.strftime("%Y%m%d")
    hh = dt_init.strftime("%H")
    return ymd, hh

def main():
    ymd = "20250626"
    hh = "18"
    model = "HYBRID"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols = 4
    npages = 4

    # --- ログ捕捉 ---
    log_buffer = StringIO()
    sys.stdout = sys.stderr = log_buffer

    print(f"[START] {ymd} Weathercaster天気図自動処理")
    print("[STEP1] GPVデータ一括ダウンロード")

    # 画像生成
    panel_imgs = generate_japan_panel_images(
        ymd=ymd, hh=hh, model=model,
        output_dir=output_dir, ncols=ncols, npages=npages
    )
    for img in panel_imgs:
        print(f"[OK] 保存: {img}")

    # ZIP作成
    print("[STEP3] JPGをZIP圧縮")
    zip_name = f"panel_japan_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_files(panel_imgs, zip_path)
    print(f"[OK] ZIP作成: {zip_path}")

    # Google Driveアップロード
    print("[STEP4] Google Driveへアップロード")
    drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
    print(f"[OK] Drive URL: {drive_url}")

    # ファイルリスト
    file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [zip_name])
    detail_log = log_buffer.getvalue()

    # Slack通知文
    msg = (
        f":earth_asia: 全国天気図パネル {ymd} UTC{hh}\n"
        "--- LOG ---\n"
        f"{file_log}\n"
    )
    send_slack_text(channel=slack_channel, message=msg)

    # 標準出力を元に戻す
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_buffer.close()

if __name__ == "__main__":
    main()
