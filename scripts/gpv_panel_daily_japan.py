# ===============================================================
# scripts/gpv_panel_daily_japan.py
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-07-01 ChatGPT（plotter_universal利用に統一）
# ===============================================================

import os
import sys
import datetime
import requests
import xarray as xr

from module.utils.slack_utils import send_slack_text
from module.core.gpv_downloader import list_files_on_server, GPV_MIRROR_URLS
from module.plotter.gpv_plotter_universal import (
    dump_grib_vars_auto,
    generate_universal_panel_and_notify,
    get_rh_fallback,
    get_apcp_3hr,
)


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

        # ダンプ（デバッグ用/本番不要ならコメント可）
        print("==== GSM L-pall dump ====")
        dump_grib_vars_auto(gsm_l_pall_path)
        print("==== MSM L-pall dump ====")
        dump_grib_vars_auto(msm_l_pall_path)
        print("==== MSM Lsurf dump ====")
        dump_grib_vars_auto(msm_lsurf_path)

        # 2. パネル生成・Driveアップ・Slack通知まで一括
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            ymd=ymd, hh=hh,
            gsm_l_pall_path=gsm_l_pall_path,
            msm_l_pall_path=msm_l_pall_path,
            msm_lsurf_path=msm_lsurf_path,
            output_dir=output_dir,
            drive_folder=drive_folder,
            ncols=4,    # 必要に応じ調整
            npages=4,   # 必要に応じ調整
            city_name="japan",   # ← **ここにカンマ！**
            rh_fallback_func=get_rh_fallback,
            apcp_3hr_func=get_apcp_3hr,
        )

        # 通知
        msg = (
            f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
            f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
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
