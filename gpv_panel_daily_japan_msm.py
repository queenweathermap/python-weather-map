# gpv_panel_daily_japan_msm.py
# ===============================================================
# MSMパネル自動生成スクリプト（GRIB2直接読取 cfgrib対応・Drive保存・Slack通知・クリーンアップ付き）
# 2025-06-22 改訂 by ChatGPT
# ===============================================================

# gpv_panel_daily_japan_msm.py
"""
全国MSM天気図6枚を縦1列で自動描画・Drive保存・Slack通知
"""

import os
import datetime
import xarray as xr
import matplotlib.pyplot as plt

# --- プロット関数群をインポート ---
from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot_surface_pressure_wind_precip import plot_surface_pressure_wind_precip

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message
from module.utils.gpv_download_utils import download_msm_grib  # 必要なら自作

def main():
    # === MSM GRIB2の取得 ===
    # grib_fname = download_msm_grib(...)  # 独自ダウンローダーを使う場合
    # ここでは過去データ手動指定
    ymd = '20240622'
    hh = '12'
    grib_fname = f"Z__C_RJTD_{ymd}{hh}0000_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin"
    if not os.path.exists(grib_fname):
        raise FileNotFoundError(grib_fname)
    ds = xr.open_dataset(grib_fname, engine='cfgrib')

    ds_surf = xr.open_dataset("Z__C_RJTD_20240622120000_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin", engine="cfgrib")

    fig, ax = plt.subplots(figsize=(8,8))
    plot_surface_pressure_wind_precip(ax, ds_surf)
    plt.show()

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

    plot_surface_pressure_wind_precip(axes[5], ds)
    axes[5].set_title("地上: 等圧線・風・降水")

    # === 保存
    now = datetime.datetime.now()
    outdir = "data"
    os.makedirs(outdir, exist_ok=True)
    out_path = os.path.join(outdir, f"msm_panel_{ymd}{hh}_{now.strftime('%Y%m%d_%H%M')}.jpg")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print("[OK] Saved:", out_path)

    # === Drive自動削除＋アップロード＋Slack通知
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
