# ===============================================================
# 秋田局地MSMパネル（エマグラム付き）自動生成・Drive+Slack通知バッチ
# 2025-06-28 改訂（全国版に完全準拠、Drive必須運用対応）
# ===============================================================

import os
import datetime
import requests
import traceback
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.slack_utils import send_slack_text

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]  # MSMの一般的なサイクル

def find_latest_available_files_akita(base_url=BASE_URL, max_days=2):
    """利用可能な最新GPVファイル（秋田局地用）を探索"""
    now = datetime.datetime.utcnow()
    for day_delta in range(max_days):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = t.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            target_init = f"{y}{m}{d}{hh}0000"
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
                return f"{y}{m}{d}", hh, file_paths
    raise FileNotFoundError("利用可能なGPVファイルが見つかりません")

def main():
    try:
        # ==== サイクル自動判定 ====
        ymd, hh, file_infos = find_latest_available_files_akita()
        model = "MSM"
        output_dir = "./output_akita"
        drive_folder = os.environ["DRIVE_FOLDER_ID"]
        slack_channel = os.environ["SLACK_CHANNEL_ID"]
        # 必要に応じてパネル分割数やcity_nameも可変化
        ncols, npages, nrows = 4, 1, 1   # 秋田局地用（必要なら調整）
        city_name = "akita"

        # ---- 必要ファイルDL（未DLのみ保存） ----
        for info in file_infos:
            if not os.path.exists(info["local"]):
                resp = requests.get(info["url"])
                if resp.status_code == 200:
                    os.makedirs(os.path.dirname(info["local"]), exist_ok=True)
                    with open(info["local"], "wb") as f:
                        f.write(resp.content)
                    print(f"[OK] DL: {info['local']}")
                else:
                    print(f"[WARN] ファイル未取得: {info['url']} (status={resp.status_code})")

        # ---- パネル生成＋Drive＋Slack通知 ----
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            ymd=ymd, hh=hh, model=model, output_dir=output_dir,
            drive_folder=drive_folder,
            ncols=ncols, npages=npages, nrows=nrows,
            city_name=city_name
        )
        msg = (
            f":red_circle: 秋田局地天気図パネル {ymd} UTC{hh}\n"
            f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
            f"{os.path.basename(zip_path)}\n"
            f"{drive_url if drive_url and drive_url not in ('未アップロード', '') else '(Driveアップロード未設定)'}"
        )
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 秋田局地パネル自動化 完了")

    except Exception as e:
        print(f"[ERROR] {e}")
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
