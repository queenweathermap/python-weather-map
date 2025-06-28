# scripts/gpv_panel_daily_local.py
# ===============================================================
# 任意局地 MSM天気図パネル（7段4列）自動生成・Drive+Slack通知バッチ
# 2025-06-28
# 緯度・経度・都市名・範囲を変えるだけで複数地点運用OK
# ===============================================================


import os
import datetime
import requests
import traceback
from module.utils.slack_utils import send_slack_text
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.panel_definitions import get_panel_def_local, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]

def find_latest_available_files_local(base_url=BASE_URL, max_days=2):
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
        ymd, hh, file_infos = find_latest_available_files_local()
        model = "MSM"
        output_dir = "./output_local"
        drive_folder = os.environ["DRIVE_FOLDER_ID"]
        slack_channel = os.environ["SLACK_CHANNEL_ID"]
        city_name = "tokyo"

        # GPVファイルDL
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

        # --- データセット読み込み ---
        l_pall_path = file_infos[0]["local"]
        lsurf_path = file_infos[1]["local"]

        ds_emagram = open_isobaric_dataset(l_pall_path)
        ds_850 = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_850_thetae = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_925 = open_isobaric_dataset(l_pall_path, hPa=925)
        ds_975 = open_isobaric_dataset(l_pall_path, hPa=975)
        ds_surface = open_surface_dataset(lsurf_path)

        # 必要なパネル構成に合わせて定義
        from module.plot.plot_emagram import plot_emagram
        from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
        from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
        from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
        from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
        from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

        custom_items = [
            (plot_emagram, ds_emagram, "エマグラム"),
            (plot_850hpa_temp_wind_700hpa_w, ds_850, "850hPa気温・風・700hPa鉛直流"),
            (plot_850hpa_thetae_stream, ds_850_thetae, "850hPa相当温位・流線"),
            (plot_925hpa_temp_wind_dindex, ds_925, "925hPa気温・風・湿数"),
            (plot_975hpa_temp_wind_dindex, ds_975, "975hPa気温・風・湿数"),
            (plot_surface_pressure_and_wind_msm, ds_surface, "地上"),
            (None, None, ""),   # 7段目は空欄
        ]
        panel_def_local = get_panel_def_local(custom_items, total_rows=7)
        extent = REGION_EXTENTS["tokyo"]

        # --- パネル生成 ---
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            model="MSM",
            output_dir=output_dir,
            drive_folder=drive_folder,
            ncols=4, npages=4,
            panel_def=panel_def_local,
            nrows=7,
            city_name=city_name,
            extent=extent,
        )

        msg = (
            f":yellow_circle: ワンポイント天気図パネル {ymd} UTC{hh}\n"
            f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
            f"{os.path.basename(zip_path)}\n"
            f"{drive_url if drive_url and drive_url not in ('未アップロード', '') else '(Driveアップロード未設定)'}"
        )
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 任意局地パネル自動化 完了")
    except Exception as e:
        print(f"[ERROR] {e}")
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
