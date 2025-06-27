# module/plotter/gpv_plotter_hybrid.py
# ===============================================================
# 日本全国・ハイブリッド（GSM+MSM）天気図パネル自動生成メイン関数
# ・GSM/MSMデータ取得・読み込み
# ・複数ページ分パネル描画
# ・jpg保存、Zip、Driveアップロード、Slack通知
# ===============================================================

import os
import datetime
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message
from module.utils.zip_utils import zip_files

from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

import cfgrib
import xarray as xr

def generate_japan_panel_and_notify(
    ymd,
    hh,
    model="HYBRID",
    output_dir="./data",
    drive_folder=None,
    ncols=4,
    npages=4,
    slack_channel=None,
):
    """
    全国パネル生成＋Zip＋Driveアップ＋Slack通知一括実行
    """
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")
    os.makedirs(output_dir, exist_ok=True)

    # --- 1. データダウンロード ---
    patterns = MODEL_CONFIG["MSM"]["patterns"]  # HYBRID時は工夫
    panel_files = download_gpv_panel(patterns, output_dir, dt, GPV_MIRROR_URLS, ncols=ncols*npages)
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        raise FileNotFoundError("GPVファイルが見つかりません")

    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]
    ds_isobaric = [d for d in cfgrib.open_datasets(l_pall_fname) if "isobaricInhPa" in d.variables][0]
    ds_surf_instant = xr.open_dataset(
        lsurf_fname, engine="cfgrib", filter_by_keys={"stepType": "instant"}
    )

    panel_def = [
        (plot_300hpa_height_wind, ds_isobaric, "300hPa高度・風"),
        (plot_500hpa_vorticity, ds_isobaric, "500hPa渦度"),
        (plot_700hpa_dindex_500hpa_temp, ds_isobaric, "700hPa湿数＋500hPa気温"),
        (plot_850hpa_temp_wind_700hpa_w, ds_isobaric, "850hPa温度・風＋700hPa鉛直流"),
        (plot_850hpa_thetae_stream, ds_isobaric, "850hPa θe流線"),
        (plot_975hpa_temp_wind_dindex, ds_isobaric, "975hPa温度・風・湿数"),
        (plot_925hpa_temp_wind_dindex, ds_isobaric, "925hPa温度・風・湿数"),
        (plot_surface_pressure_and_wind_msm, ds_surf_instant, "地上気圧・風・降水"),
    ]

    # --- 2. 画像ページ分割描画 ---
    panel_imgs = []
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=len(panel_def), ncols=ncols,
            figsize=(ncols*3, len(panel_def)*3),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )
        for row, (plot_func, ds, title) in enumerate(panel_def):
            n_steps = ds.dims["step"] if "step" in ds.dims else 1
            for col in range(ncols):
                step = page * ncols + col
                if step >= n_steps:
                    axes[row, col].axis("off")
                    axes[row, col].set_title(f"{title} (no data)")
                    continue
                try:
                    ds_step = ds.isel(step=step)
                    plot_func(axes[row, col], ds_step)
                    axes[row, col].set_title(f"{title} (+{step*3}h)")
                except Exception as e:
                    axes[row, col].set_title(f"{title} (エラー)")
                    print(f"[ERROR] {title}: {e}")
                    axes[row, col].axis("off")

        page_time_range = f"{ymd} {hh}00 +{page*ncols*3}h〜+{(page+1)*ncols*3-3}h"
        fig.suptitle(f"全国天気図パネル（{page_time_range}）", fontsize=20)
        out_name = f"panel_japan_{ymd}{hh}_p{page+1}.jpg"
        out_path = os.path.join(output_dir, out_name)
        plt.savefig(out_path, dpi=300)
        plt.close()
        print("[OK] Saved:", out_path)
        panel_imgs.append(out_path)

    # --- 3. ZIP圧縮 ---
    zip_path = os.path.join(output_dir, f"panel_japan_{ymd}{hh}.zip")
    zip_files(panel_imgs, zip_path)

    # --- 4. Google Driveにアップロード ---
    drive_url = "(未アップロード)"
    if drive_folder:
        delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
        drive_url = upload_to_drive(zip_path, folder_id=drive_folder)

    # --- 5. Slack通知 ---
    msg = (
        f":チェックマーク_緑: 全国天気図パネル {ymd} UTC{hh} \n"
        f"Google Driveリンク（JPG ZIP）:\n"
        f"{drive_url}\n"
        "--- LOG ---\n"
        f"ファイル名 {ymd}_UTC{hh}.jpg"
    )
    send_slack_message(msg)

    print("[DONE] 全国天気図パネルの自動生成・通知が完了しました")
