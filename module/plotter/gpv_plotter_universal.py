# module/plotter/gpv_plotter_universal.py
# ===============================================================
# 全国・秋田・任意局地ハイブリッド天気図パネル生成・通知コア
# city_name・extentの柔軟指定対応
# 2025-06-28 by ChatGPT
# ===============================================================

import os
import datetime
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cfgrib
import xarray as xr

from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files

# --- 地域ごとのデフォルトズーム範囲定義 ---
REGION_EXTENTS = {
    "japan": [122, 153, 20, 46],
    "akita": [139.5, 141.0, 38.8, 40.5],
    "tokyo": [138.5, 140.0, 34.7, 36.2],
    # 必要に追加
}

def generate_universal_panel_and_notify(
    ymd, hh, model, output_dir,
    drive_folder=None,
    ncols=4, npages=1, nrows=None,
    panel_def=None,
    city_name="japan",
    extent=None,    # ★任意範囲を直接指定したい場合
    slack_channel=None,
    log_callback=None,
):
    """
    描画範囲は city_name で自動切替。直接 extent で上書きも可能。
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")

    # --- データダウンロード（省略: 必要に応じてカスタムダウンロード処理） ---
    patterns = MODEL_CONFIG.get(model, MODEL_CONFIG["MSM"])["patterns"]
    panel_files = download_gpv_panel(patterns, output_dir, dt, GPV_MIRROR_URLS, ncols=ncols*npages)
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        log("[ERROR] GPVファイルが見つかりません")
        raise FileNotFoundError("GPVファイルが見つかりません")

    # --- データセット取得 ---
    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]
    ds_isobaric = open_isobaric_dataset(l_pall_fname)
    ds_surf_instant = open_surface_dataset(lsurf_fname)

    # --- パネル定義 ---
    if panel_def is None:
        from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
        from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
        from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
        from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
        from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
        from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
        from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
        from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

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
        nrows = len(panel_def)

    # --- 範囲選択（city_name優先・直接渡しなら上書き） ---
    extent = extent or REGION_EXTENTS.get(city_name, REGION_EXTENTS["japan"])

    # --- 描画 ---
    panel_imgs = []
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=nrows, ncols=ncols,
            figsize=(ncols*3, nrows*3),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )
        for row, (plot_func, ds, title) in enumerate(panel_def):
            n_steps = ds.dims["step"] if "step" in ds.dims else 1
            for col in range(ncols):
                step = page * ncols + col
                ax = axes[row, col]
                ax.set_extent(extent, crs=ccrs.PlateCarree())
                if step >= n_steps:
                    ax.axis("off")
                    ax.set_title(f"{title} (no data)")
                    continue
                try:
                    ds_step = ds.isel(step=step)
                    if plot_func:
                        plot_func(ax, ds_step)
                    ax.set_title(f"{title} (+{step*3}h)")
                except Exception as e:
                    ax.set_title(f"{title} (エラー)")
                    log(f"[ERROR] {title}: {e}")
                    ax.axis("off")
        fig.suptitle(f"{city_name}天気図パネル（{ymd} UTC{hh}）", fontsize=20)
        out_name = f"panel_{city_name}_{ymd}_UTC{hh}_p{page+1}.jpg"
        out_path = os.path.join(output_dir, out_name)
        plt.savefig(out_path, dpi=300)
        plt.close()
        log(f"[OK] 保存: {out_path}")
        panel_imgs.append(out_path)

    # --- ZIP & Drive ---
    zip_name = f"panel_{city_name}_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_files(panel_imgs, zip_path)
    drive_url = "(未アップロード)"
    if drive_folder:
        delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
        drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
        log(f"[OK] Drive URL: {drive_url}")

    return panel_imgs, zip_path, drive_url
