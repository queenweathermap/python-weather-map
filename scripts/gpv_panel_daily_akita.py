# ===============================================================
# 秋田局地MSMパネル（エマグラム付き）自動生成・Drive+Slack通知バッチ
# 2025-06-28 改訂（全国版に完全準拠、Drive必須運用対応）
# ===============================================================

import os
import datetime
import requests
import traceback
from module.utils.slack_utils import send_slack_text
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.panel_definitions import get_panel_def_akita, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset  # 追加

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]

def find_latest_available_files_akita(base_url=BASE_URL, max_days=2):
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
        ymd, hh, file_infos = find_latest_available_files_akita()
        model = "MSM"
        output_dir = "./output_akita"
        drive_folder = os.environ["DRIVE_FOLDER_ID"]
        slack_channel = os.environ["SLACK_CHANNEL_ID"]
        city_name = "akita"

        # --- GPVファイルDL ---
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

        # --- ファイル仕分け ---
        l_pall_path = None
        lsurf_path = None
        for info in file_infos:
            fname = info["local"]
            if "MSM_GPV_Rjp_L-pall" in fname:
                l_pall_path = fname
            elif "MSM_GPV_Rjp_Lsurf" in fname:
                lsurf_path = fname

        if not (l_pall_path and lsurf_path):
            raise FileNotFoundError(f"必要なMSM GPVファイルが不足: l_pall={l_pall_path}, lsurf={lsurf_path}")

        # --- データセット抽出（気圧面ごとに分離） ---
        ds_emagram = open_isobaric_dataset(l_pall_path)
        ds_850 = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_850_thetae = open_isobaric_dataset(l_pall_path, hPa=850)  # 必要に応じて独自抽出へ
        ds_925 = open_isobaric_dataset(l_pall_path, hPa=925)
        ds_975 = open_isobaric_dataset(l_pall_path, hPa=975)
        ds_surface = open_surface_dataset(lsurf_path)

        panel_def_akita = get_panel_def_akita(ds_emagram, ds_850, ds_850_thetae, ds_925, ds_975, ds_surface)
        extent = REGION_EXTENTS["akita"]

        # --- パネル生成（7段×4列×4ページ） ---
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            model="MSM",
            output_dir=output_akita,
            drive_folder=drive_folder,
            ncols=4, npages=4,
            panel_def=panel_def_akita,
            nrows=7,
            city_name=city_name,
            extent=extent,
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
        import traceback; traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
