# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知
# 2025-06-27 ChatGPT 新core設計準拠・最新イニシャル自動判定付き
# ===============================================================

import os
import glob
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
    # ==== 設定 ====
    ymd, hh = get_latest_gpv_init()  # ← 最新イニシャル自動取得
    model = "HYBRID"
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols = 4
    npages = 4

    # ==== ① 全国パネル生成＋Driveアップ＋Slack通知＋ログ ====
    log_lines = []
    def log(msg):
        print(msg)
        log_lines.append(msg)

    # パネル生成＆連携（ファイル名は panel_japan_{ymd}_UTC{hh}_pX.jpg 統一）
    panel_imgs = generate_japan_panel_images( # <- 画像リストだけ返すようにする
        ymd=ymd,
        hh=hh,
        model=model,
        output_dir=output_dir,
        ncols=ncols,
        npages=npages,
    )

    # ZIP作成
    zip_path = os.path.join(output_dir, f"panel_japan_{ymd}_UTC{hh}.zip")
    zip_files(panel_imgs, zip_path)
    # Drive
    drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
    # LOG
    file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [os.path.basename(zip_path)])
    msg = (
        f":earth_asia: 全国天気図パネル {ymd} UTC{hh}\n"
        f"Google Driveリンク（JPG ZIP）:\n{drive_url}\n"
        "--- LOG ---\n"
        f"{file_log}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
