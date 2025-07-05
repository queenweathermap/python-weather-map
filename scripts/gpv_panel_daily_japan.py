# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 1stepずつJPG出力→ZIP化→Driveアップ→Slack通知
# 2025-07-01 ChatGPT
# ===============================================================
import module.utils.slack_utils as s
print(dir(s))
import os
import sys
import datetime
import warnings
import gc
import zipfile
import argparse
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)

from module.utils.slack_utils import send_slack_text
from module.core.gpv_downloader import GPV_MIRROR_URLS
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.plotter.gpv_plotter_universal import open_grib2_var_auto, make_universal_weather_panel


def find_and_download_gpv_files(
    base_dir="./data",
    days_back=2,
    cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
    fh_band_gsm="FD0000-0100",
    fh_band_msm="FH00-15"
):
    base_url = GPV_MIRROR_URLS[0]
    now = datetime.datetime.utcnow()
    for day_delta in range(days_back):
        day = now - datetime.timedelta(days=day_delta)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = dt.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            from module.core.gpv_downloader import list_files_on_server
            gsm_files = list_files_on_server(dt, "GSM_GPV_Rjp_Gll0p1deg_L-pall", fh_band_gsm)
            msm_l_pall_files = list_files_on_server(dt, "MSM_GPV_Rjp_L-pall", fh_band_msm)
            msm_lsurf_files  = list_files_on_server(dt, "MSM_GPV_Rjp_Lsurf", fh_band_msm)
            if gsm_files and msm_l_pall_files and msm_lsurf_files:
                gsm_l_pall_fname = gsm_files[0]
                msm_l_pall_fname = msm_l_pall_files[0]
                msm_lsurf_fname  = msm_lsurf_files[0]
                file_paths = []
                import requests
                for fname in [gsm_l_pall_fname, msm_l_pall_fname, msm_lsurf_fname]:
                    url = f"{data_url}{fname}"
                    local = os.path.join(base_dir, fname)
                    if not os.path.exists(local):
                        resp = requests.get(url)
                        if resp.status_code == 200:
                            os.makedirs(os.path.dirname(local), exist_ok=True)
                            with open(local, "wb") as f:
                                f.write(resp.content)
                            print(f"[OK] DL: {local}")
                        else:
                            print(f"[NG] DL: {url} (status={resp.status_code})")
                            break
                    file_paths.append(local)
                if len(file_paths) == 3:
                    return y+m+d, hh, file_paths
    raise FileNotFoundError("利用可能なGSM/MSM GPVファイルがindex.html上に見つかりません")

def main():
    import matplotlib
    matplotlib.use("Agg")

    parser = argparse.ArgumentParser()
    parser.add_argument('--forecast_hour', type=int, default=0)
    args = parser.parse_args()
    forecast_hour = args.forecast_hour

    print(f"[INFO] forecast_hour={forecast_hour}")

    base_dir = "./data"
    output_dir = "./output"
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")
    days_back = 2

    try:
        # 1. ファイルDL＆パス取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir, days_back=days_back
        )

        # 2. step数取得
        arr_sample = open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric")
        nsteps = arr_sample.sizes["step"] if "step" in arr_sample.sizes else 9
        del arr_sample
        gc.collect()

        # 3. forecast_hour→step変換
        step = forecast_hour // 3
        if step >= nsteps or step < 0:
            raise ValueError(f"指定のforecast_hour({forecast_hour})が有効な範囲外です（nsteps={nsteps})")

        # 必要変数をstepごとにopen
        panel_datasets = {
            "gh_300": open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "u_300":  open_grib2_var_auto("u", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "v_300":  open_grib2_var_auto("v", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "gh_500": open_grib2_var_auto("gh", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "u_500":  open_grib2_var_auto("u", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "v_500":  open_grib2_var_auto("v", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "t_700":  open_grib2_var_auto("t", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "r_700":  open_grib2_var_auto("r", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "t_500":  open_grib2_var_auto("t", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "t_850":  open_grib2_var_auto("t", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "u_850":  open_grib2_var_auto("u", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "v_850":  open_grib2_var_auto("v", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "w_700":  open_grib2_var_auto("w", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "r_850":  open_grib2_var_auto("r", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "prmsl":  open_grib2_var_auto("prmsl", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
            "u10":    open_grib2_var_auto("u10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
            "v10":    open_grib2_var_auto("v10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
        }

        panel_def = get_panel_def_japan(panel_datasets)
        ncols = 1
        nrows = len(panel_def)
        extent = REGION_EXTENTS["japan"]
        img_path = f"{output_dir}/panel_japan_{ymd}_UTC{hh}_fh{forecast_hour:02}.jpg"
        panel_imgs = make_universal_weather_panel(
            save_dir=output_dir,
            panel_def=panel_def,
            times=None,
            init_time_str=f"{ymd}_UTC{hh}",
            city_name="japan",
            ncols=ncols,
            nrows=nrows,
            extent=extent,
            dpi=80,
            step=step
        )
        try:
            if panel_imgs and os.path.exists(panel_imgs[0]):
                os.rename(panel_imgs[0], img_path)
                print(f"[OK] 画像保存: {img_path}")

                drive_url = upload_to_drive(img_path, folder="DRIVE_FOLDER_ID")
                print(f"[OK] Drive URL: {drive_url}")

                msg = (
                    f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh} +{forecast_hour}h\n"
                    f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
                    f"{os.path.basename(img_path)}\n"
                    f"{drive_url if drive_url and drive_url not in ('未アップロード', '') else '(Driveアップロード未設定)'}"
                )
                send_slack_text(channel=slack_channel, message=msg)

                delete_old_files_from_drive(days=30, folder="DRIVE_FOLDER_ID")

            else:
                send_slack_text(channel=slack_channel, message=":x: 画像ファイル生成に失敗しました")
                raise RuntimeError("画像ファイル生成に失敗しました")

    except Exception as e:
        msg = f":x: パネル生成失敗: {e}"
        send_slack_text(channel=slack_channel, message=msg)
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
