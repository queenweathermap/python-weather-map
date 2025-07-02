# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-07-01 ChatGPT（plotter_universal利用に統一／1枚出力版）
# ===============================================================

import os
import sys
import glob
import datetime
import requests
import xarray as xr
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

from module.utils.slack_utils import send_slack_text
from module.core.gpv_downloader import list_files_on_server, GPV_MIRROR_URLS
from module.plotter.gpv_plotter_universal import (
    make_universal_weather_panel,
    get_rh_fallback,
    get_apcp_3hr,
)
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.panel_utils import concat_panel_images_horizontally

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
            gsm_files = list_files_on_server(dt, "GSM_GPV_Rjp_Gll0p1deg_L-pall", fh_band_gsm)
            msm_l_pall_files = list_files_on_server(dt, "MSM_GPV_Rjp_L-pall", fh_band_msm)
            msm_lsurf_files  = list_files_on_server(dt, "MSM_GPV_Rjp_Lsurf", fh_band_msm)
            if gsm_files and msm_l_pall_files and msm_lsurf_files:
                gsm_l_pall_fname = gsm_files[0]
                msm_l_pall_fname = msm_l_pall_files[0]
                msm_lsurf_fname  = msm_lsurf_files[0]
                file_paths = []
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
    base_dir = "./data"
    output_dir = "./output"
    drive_folder = os.environ.get("DRIVE_FOLDER_ID")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")
    days_back = 2

    try:
        # 1. 必要ファイルDL＆パス取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir, days_back=days_back
        )

        # 2. データ抽出（パネル定義取得に必要なdictを構築）
        from module.plotter.gpv_plotter_universal import open_grib2_var_auto

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
            "prmsl": open_grib2_var_auto("prmsl", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
            "u10":   open_grib2_var_auto("u10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
            "v10":   open_grib2_var_auto("v10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
            "apcp":  open_grib2_var_auto("apcp", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        }
        panel_def = get_panel_def_japan(panel_datasets)

        # 3. 各step（列）ごとに6段1列パネル画像（複数）を生成
        ncols = 1              # 1列出力
        nrows = len(panel_def) # 6段
        nsteps = 3             # ←2ステップ分生成
        extent = REGION_EXTENTS["japan"]
        init_time_str = f"{ymd}_UTC{hh}"
        
        panel_img_paths = []
        for step in range(nsteps):
            img_path = f"{output_dir}/panel_japan_{ymd}_UTC{hh}_p{step+1}.jpg"
            panel_imgs = make_universal_weather_panel(
                save_dir=output_dir,
                panel_def=panel_def,
                times=None,  # 必要なら stepごとに時刻リストを与える
                init_time_str=f"{init_time_str}_p{step+1}",
                city_name="japan",
                ncols=ncols,
                nrows=nrows,
                extent=extent,
                dpi=300
            )
            # ファイル名リネーム/保存
            if panel_imgs and os.path.exists(panel_imgs[0]):
                os.rename(panel_imgs[0], img_path)
                panel_img_paths.append(img_path)
        
        # 4. 横方向に画像を結合（full.jpgを生成）
        full_path = f"{output_dir}/panel_japan_{ymd}_UTC{hh}_full.jpg"
        if panel_img_paths:
            concat_panel_images_horizontally(panel_img_paths, full_path)
            panel_img_path = full_path
        else:
            raise RuntimeError("6段1列画像が1枚も生成されませんでした")


        
        # 5. Driveアップ（full.jpgだけ）
        if drive_folder:
            delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
            drive_url = upload_to_drive(panel_img_path, folder_id=drive_folder)
        else:
            drive_url = "(未アップロード)"

        # 6. Slack通知
        msg = (
            f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
            f"{os.path.basename(panel_img_path)}\n"
            f"{drive_url if drive_url else '(Driveアップロード失敗)'}"
        )
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 全国パネル自動化 完了")

    except FileNotFoundError:
        send_slack_text(channel=slack_channel, message=":warning: 必要なGPVファイルが見つかりません（GSM/MSM/Lsurf）")
        sys.exit(1)
    except Exception as e:
        send_slack_text(channel=slack_channel, message=f":x: パネル生成失敗: {e}")
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
