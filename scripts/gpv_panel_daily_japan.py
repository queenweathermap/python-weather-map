# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Zip＋Drive＋Slack通知
# 2025-06-27 ChatGPT 新core設計準拠・最新イニシャル自動判定付き
# ===============================================================

# scripts/gpv_panel_daily_japan.py
import os
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.slack_utils import send_slack_text

def main():
    # 最新イニシャル取得
    import datetime
    now = datetime.datetime.utcnow()
    ymd = now.strftime("%Y%m%d")
    hh = f"{(now.hour//3)*3:02d}"  # 直近3時間単位

    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]

    panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
        ymd=ymd, hh=hh,
        model="HYBRID",
        output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=4, npages=4, nrows=8,
        city_name=None,
        slack_channel=slack_channel,
    )
    # Slack通知例
    file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [os.path.basename(zip_path)])
    msg = (
        f":earth_asia: 全国天気図パネル {ymd} UTC{hh}\n"
        "--- LOG ---\n"
        f"{file_log}\n"
        f"{drive_url}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
