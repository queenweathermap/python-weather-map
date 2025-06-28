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

def find_latest_available_files_japan(base_url=BASE_URL, max_days=2):
    """
    利用可能な最新GPVファイル（全国用/GSM+MSM両方）を探索
    GSMは複数パターンで探索し、最初に見つかったものを採用
    """
    now = datetime.datetime.utcnow()
    for day_delta in range(max_days):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = t.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            target_init = f"{y}{m}{d}{hh}0000"

            # --- GSMパターン拡張 ---
            gsm_patterns = [
                f"Z__C_RJTD_{target_init}_GSM_GPV_Rjp_L-pall_FD0000_grib2.bin",
                f"Z__C_RJTD_{target_init}_GSM_GPV_Rjp_L-pall_FD0000-0100_grib2.bin",
                f"Z__C_RJTD_{target_init}_GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000_grib2.bin",
                f"Z__C_RJTD_{target_init}_GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin"
            ]
            # MSMパターン
            msm_patterns = [
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin"
            ]

            gsm_found, msm_found = None, []
            # --- GSM探索 ---
            for fname in gsm_patterns:
                url = f"{data_url}{fname}"
                try:
                    r = requests.head(url, timeout=5)
                    if r.status_code == 200:
                        gsm_found = {"url": url, "local": os.path.join("./data", fname)}
                        break
                except Exception:
                    continue

            # --- MSM探索 ---
            for fname in msm_patterns:
                url = f"{data_url}{fname}"
                try:
                    r = requests.head(url, timeout=5)
                    if r.status_code == 200:
                        msm_found.append({"url": url, "local": os.path.join("./data", fname)})
                except Exception:
                    continue

            # --- 全部揃ったらreturn ---
            if gsm_found and len(msm_found) == 2:
                return y + m + d, hh, [gsm_found] + msm_found

    raise FileNotFoundError("利用可能なGSM+MSM GPVファイルが見つかりません")

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
            print(f"[WARN] GSMファイルが未取得です。全国パネル（GSM+MSM）は作成されません。")
            msg = f":warning: GSMファイル未取得のため全国パネル（{ymd} UTC{hh}）はスキップされました。"
            send_slack_text(channel=slack_channel, message=msg)
            return
        
        if not (msm_l_pall_path and msm_lsurf_path):
            raise FileNotFoundError(f"必要なMSM GPVファイルが不足: msm_l_pall={msm_l_pall_path}, msm_lsurf={msm_lsurf_path}")

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
        exit(1)

if __name__ == "__main__":
    main()
