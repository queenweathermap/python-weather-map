# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-28
# ===============================================================

import os
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.slack_utils import send_slack_text

def find_latest_available_files_japan(base_url=BASE_URL, max_days=2):
    """利用可能な最新GPVファイルを全国用に探索"""
    now = datetime.datetime.utcnow()
    # GSMなら 00, 06, 12, 18、MSMなら 21,18,15... などモデルごとにサイクル指定
    CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]  # MSM例（GSMは6時間毎）
    for day_delta in range(max_days):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = t.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            target_init = f"{y}{m}{d}{hh}0000"
            # 全国用で必要なファイルリストをここに
            file_patterns = [
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin"
            ]
            file_paths = []
            found = False
            for fname in file_patterns:
                url = f"{data_url}{fname}"
                r = requests.head(url, timeout=5)
                if r.status_code == 200:
                    found = True
                    file_paths.append({"url": url, "local": os.path.join("./data", fname)})
            if found:
                return y, m, d, hh, file_paths
    raise FileNotFoundError("利用可能なGPVファイルが見つかりません")


def main():
    # ==== 設定値 ====
    ymd = "20250628"              # 例: 実運用時は最新イニシャル自動化OK
    hh = "00"
    model = "HYBRID"              # GSM/MSM/HYBRID
    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    ncols, npages, nrows = 4, 4, 7
    city_name = "japan"

    # --- 一括パネル生成＋Drive＋URL取得 ---
    panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
        ymd=ymd, hh=hh, model=model, output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=ncols, npages=npages, nrows=nrows,
        city_name=city_name
    )

    # --- Slack通知 ---
    msg = (
        f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
        f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
        f"{os.path.basename(zip_path)}\n"
        f"{drive_url}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
