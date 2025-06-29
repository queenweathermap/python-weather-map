# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-28 改訂（panel_definitions準拠）
# ===============================================================

import os
import datetime
import requests
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.utils.slack_utils import send_slack_text

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]  # MSM/実用運用用。GSMも00/06/12/18でOK

from module.core.gpv_downloader import list_files_on_server, GPV_MIRROR_URLS

def find_latest_available_files_japan(base_dir="./data", days_back=2):
    """index.htmlをパースしてGSM/MSMの最新ファイルを抽出する"""
    base_url = GPV_MIRROR_URLS[0]
    now = datetime.datetime.utcnow()
    CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]
    gsm_pattern = "GSM_GPV_Rjp_Gll0p1deg_L-pall"
    msm_l_pall_pattern = "MSM_GPV_Rjp_L-pall"
    msm_lsurf_pattern = "MSM_GPV_Rjp_Lsurf"
    fh_band_gsm = "FD0000-0100"
    fh_band_msm = "FH00-15"
    
    for day_delta in range(days_back):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            gsm_files = list_files_on_server(dt, gsm_pattern, fh_band_gsm)
            msm_l_pall_files = list_files_on_server(dt, msm_l_pall_pattern, fh_band_msm)
            msm_lsurf_files  = list_files_on_server(dt, msm_lsurf_pattern, fh_band_msm)
            if gsm_files and msm_l_pall_files and msm_lsurf_files:
                y, m, d, hh = dt.strftime("%Y %m %d %H").split()
                data_url = f"{base_url}/{y}/{m}/{d}/"
                gsm_fname = gsm_files[0]
                msm_l_pall_fname = msm_l_pall_files[0]
                msm_lsurf_fname  = msm_lsurf_files[0]
                file_infos = [
                    {"url": f"{data_url}{gsm_fname}", "local": os.path.join(base_dir, gsm_fname)},
                    {"url": f"{data_url}{msm_l_pall_fname}", "local": os.path.join(base_dir, msm_l_pall_fname)},
                    {"url": f"{data_url}{msm_lsurf_fname}", "local": os.path.join(base_dir, msm_lsurf_fname)},
                ]
                return y+m+d, hh, file_infos
    raise FileNotFoundError("利用可能なGSM/MSM GPVファイルがindex.html上に見つかりません")

def main():
    try:
        ymd, hh, file_infos = find_latest_available_files_japan()
        model = "HYBRID"
        output_dir = "./data"
        drive_folder = os.environ["DRIVE_FOLDER_ID"]
        slack_channel = os.environ["SLACK_CHANNEL_ID"]
        city_name = "japan"
        ncols, npages = 4, 4

        # --- 必要ファイルDL ---
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

        # --- ファイル名を自動で仕分け ---
        gsm_l_pall_path = None
        msm_l_pall_path = None
        msm_lsurf_path = None
        for info in file_infos:
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
            from module.utils.slack_utils import send_slack_text
            send_slack_text(channel=slack_channel, message=msg)
            import sys
            sys.exit(1)  # スキップ禁止・確実に止める

        if not (msm_l_pall_path and msm_lsurf_path):
            msg = (f":warning: 必要なMSM GPVファイルが不足: msm_l_pall={msm_l_pall_path}, "
                   f"msm_lsurf={msm_lsurf_path}\n全国パネル生成は**中止**します（強制終了）")
            print(msg)
            from module.utils.slack_utils import send_slack_text
            send_slack_text(channel=slack_channel, message=msg)
            import sys
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
        from module.utils.slack_utils import send_slack_text
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 全国パネル自動化 完了")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()
