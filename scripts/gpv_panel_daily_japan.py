# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-29 最新版（fail-fastスキップ禁止・panel_definitions準拠）
# ===============================================================

import os
import sys
import datetime
import requests
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.utils.slack_utils import send_slack_text
from module.gpv_download_utils import find_latest_available_files_for_model
from module.core.gpv_downloader import MODEL_CONFIG, list_files_on_server, GPV_MIRROR_URLS

def main():
    base_dir = "./data"
    days_back = 2
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    output_dir = "./data"
    city_name = "japan"
    ncols, npages = 4, 4
    model = "HYBRID"

    try:
        # ---- GSM取得
        ymd, hh, gsm_file_infos = find_latest_available_files_for_model(
            base_dir=base_dir,
            mirrors=GPV_MIRROR_URLS,
            model_patterns=MODEL_CONFIG["GSM"]["patterns"],
            fh_band="FD0000-0100",
            cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
            days_back=days_back,
            list_files_func=list_files_on_server
        )

        # ---- MSM取得
        _, _, msm_file_infos = find_latest_available_files_for_model(
            base_dir=base_dir,
            mirrors=GPV_MIRROR_URLS,
            model_patterns=MODEL_CONFIG["MSM"]["patterns"],
            fh_band="FH00-15",
            cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
            days_back=days_back,
            list_files_func=list_files_on_server
        )

        # ---- 必要ならDL
        for info in gsm_file_infos + msm_file_infos:
            if not os.path.exists(info["local"]):
                resp = requests.get(info["url"])
                if resp.status_code == 200:
                    os.makedirs(os.path.dirname(info["local"]), exist_ok=True)
                    with open(info["local"], "wb") as f:
                        f.write(resp.content)
                    print(f"[OK] DL: {info['local']}")
                else:
                    print(f"[NG] DL: {info['url']} (status={resp.status_code})")

        # --- ファイル名を自動で仕分け ---
        gsm_l_pall_path = None
        msm_l_pall_path = None
        msm_lsurf_path = None
        for info in gsm_file_infos + msm_file_infos:
            fname = info["local"]
            if "GSM_GPV_Rjp_L-pall" in fname:
                gsm_l_pall_path = fname
            elif "MSM_GPV_Rjp_L-pall" in fname:
                msm_l_pall_path = fname
            elif "MSM_GPV_Rjp_Lsurf" in fname:
                msm_lsurf_path = fname

        # --- ファイルが全部揃っているかチェック ---
        if not gsm_l_pall_path:
            msg = f":warning: GSMファイル未取得のため全国パネル（{ymd} UTC{hh}）は**中止**されました（強制終了）"
            print(msg)
            send_slack_text(channel=slack_channel, message=msg)
            sys.exit(1)

        if not (msm_l_pall_path and msm_lsurf_path):
            msg = (f":warning: 必要なMSM GPVファイルが不足: msm_l_pall={msm_l_pall_path}, "
                   f"msm_lsurf={msm_lsurf_path}\n全国パネル生成は**中止**します（強制終了）")
            print(msg)
            send_slack_text(channel=slack_channel, message=msg)
            sys.exit(1)

        # --- データセットをモデル別に作成 ---
        ds_gsm_isobaric = open_isobaric_dataset(gsm_l_pall_path)
        ds_msm_isobaric = open_isobaric_dataset(msm_l_pall_path)
        ds_msm_surf_instant = open_surface_dataset(msm_lsurf_path)

        # --- パネル定義 ---
        panel_def = get_panel_def_japan(ds_gsm_isobaric, ds_msm_isobaric, ds_msm_surf_instant)
        extent = REGION_EXTENTS["japan"]

        # --- パネル生成 ---
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            model=model,
            output_dir=output_dir,
            drive_folder=drive_folder,
            ncols=ncols,
            npages=npages,
            nrows=len(panel_def),
            panel_def=panel_def,
            city_name=city_name,
            extent=extent,
        )
        msg = (
            f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
            f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
            f"{os.path.basename(zip_path)}\n"
            f"{drive_url if drive_url else '(Driveアップロード未設定)'}"
        )
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 全国パネル自動化 完了")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
