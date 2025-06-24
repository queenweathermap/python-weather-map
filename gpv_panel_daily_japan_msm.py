# gpv_panel_daily_japan_msm.py
# ===============================================================
# MSMパネル自動生成スクリプト（GRIB2ダウンロード・cfgrib対応・Drive保存・Slack通知・クリーンアップ付き）
# 2025-06-23 ChatGPT改訂
# ===============================================================

import os
import datetime
import xarray as xr
import matplotlib.pyplot as plt

from gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS

from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message

def main():
    # === 日時指定 ===
    ymd = '20240622'
    hh = '12'
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")
    base_dir = "./data"
    os.makedirs(base_dir, exist_ok=True)

    # === MSMのL-pall/Lsurfを自動ダウンロード ===
    patterns = MODEL_CONFIG["MSM"]["patterns"]   # ["MSM_GPV_Rjp_L-pall", "MSM_GPV_Rjp_Lsurf"]
    panel_files = download_gpv_panel(patterns, base_dir, dt, GPV_MIRROR_URLS, ncols=1)

    # パネル用ファイルが揃っているか
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        raise FileNotFoundError("必要なMSMファイルが見つかりません")

    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]

    # === データ読み込み ===
    ds = xr.open_dataset(l_pall_fname, engine="cfgrib")
    ds_surf = xr.open_dataset(lsurf_fname, engine="cfgrib")

    # === パネル作成 ===
    fig, axes = plt.subplots(nrows=6, ncols=1, figsize=(8, 48), constrained_layout=True)
    fig.suptitle(f"MSM日本全域 天気図6種 {ymd} {hh}00", fontsize=22)

    plot_700hpa_dindex_500hpa_temp(axes[0], ds)
    axes[0].set_title("700hPa D-index / 500hPa 気温")

    plot_850hpa_temp_wind_700hpa_w(axes[1], ds)
    axes[1].set_title("850hPa気温・風 + 700hPa鉛直流")

    plot_850hpa_thetae_stream(axes[2], ds)
    axes[2].set_title("850hPa θe + Stream")

    plot_975hpa_temp_wind_dindex(axes[3], ds)
    axes[3].set_title("975hPa気温・風・D-index")

    plot_925hpa_temp_wind_dindex(axes[4], ds)
    axes[4].set_title("925hPa気温・風・D-index")

    plot_surface_pressure_and_wind_msm(axes[5], ds_surf)
    axes[5].set_title("地上: 等圧線・風・降水")

    # === 保存 ===
    now = datetime.datetime.now()
    out_path = os.path.join(base_dir, f"msm_panel_{ymd}{hh}_{now.strftime('%Y%m%d_%H%M')}.jpg")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print("[OK] Saved:", out_path)

    # === Driveクリーンアップ・アップロード・Slack通知 ===
    delete_old_files_from_drive(
        folder_id=os.environ["DRIVE_FOLDER_ID"],
        creds_json=os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        days=30
    )
    gdrive_url = upload_to_drive(out_path)
    msg = f"【自動配信】MSM全国天気図6種パネル ({ymd} {hh}:00)\n{gdrive_url}"
    send_slack_message(msg)

if __name__ == "__main__":
    main()
