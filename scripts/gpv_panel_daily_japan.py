# ===============================================================
# scripts/gpv_panel_daily_japan.py
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-30 現場運用・1枚8列6段パネル・イニシャル時刻ファイル名右上表示
# ===============================================================

import os
import sys
import datetime
import requests
import xarray as xr

from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan
from module.panel_utils import make_universal_weather_panel
from module.utils.slack_utils import send_slack_text
from module.core.gpv_downloader import list_files_on_server, GPV_MIRROR_URLS

# --- GPVファイルの自動探索＆ダウンロード ---
def find_and_download_gpv_files(
    base_dir="./data",
    days_back=2,
    cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
    fh_band_gsm="FD0000-0100",
    fh_band_msm="FH00-15"
):
    """
    GSMとMSMの最新イニシャル時刻の必要ファイル3種をDL＆返却（パス3つ）
    """
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

# --- メインバッチ処理 ---
def main():
    base_dir = "./data"
    output_dir = "./output"
    drive_folder = os.environ.get("DRIVE_FOLDER_ID")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")
    days_back = 2

    try:
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir, days_back=days_back
        )
    except FileNotFoundError:
        send_slack_text(channel=slack_channel, message=":warning: 必要なGPVファイルが見つかりません（GSM/MSM/Lsurf）")
        sys.exit(1)

    # --- データセットをxarrayで開く ---
    try:
        ds_gsm_isobaric = xr.open_dataset(gsm_l_pall_path, engine="cfgrib")
        ds_msm_isobaric = xr.open_dataset(msm_l_pall_path, engine="cfgrib")
        ds_msm_surf_instant = xr.open_dataset(msm_lsurf_path, engine="cfgrib")

        # --- パネル定義（6段）---
        panel_def = get_panel_def_japan(ds_gsm_isobaric, ds_msm_isobaric, ds_msm_surf_instant)
        times = []  # 時系列が不要なら空リストでOK

        # --- イニシャル時刻をファイル名に利用 ---
        init_time_str = f"{ymd}_{hh}UTC"

        # --- パネル画像を「6段×8列×1枚」で出力 ---
        panel_imgs = make_universal_weather_panel(
            save_dir=output_dir,
            panel_def=panel_def,
            times=times,
            init_time_str=init_time_str,          # ← ヘッダ（右上）に記載
            city_name="japan",
            ncols=8,                              # 8列
            nrows=6,                              # 6段
            extent=REGION_EXTENTS["japan"],       # 描画範囲
            dpi=300                               # 高解像度・iPad最適
        )

        # --- Slack通知（必要に応じてGoogle Drive連携も）---
        msg = (
            f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
            f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
            f"{'(Driveアップロード未設定)'}"  # Drive運用する場合はURLをここに入れる
        )
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 全国パネル自動化 完了")

    except Exception as e:
        send_slack_text(channel=slack_channel, message=f":x: パネル生成失敗: {e}")
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
