# ===============================================================
# 全国・秋田・任意局地ハイブリッド天気図パネル自動生成コア
# city_nameによる地図範囲切り替え対応（2025-06-28修正版）
# ===============================================================

import os
import datetime
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cfgrib
import xarray as xr

from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files

# ▼--- 地域ごとの描画範囲を定義 ---▼
REGION_EXTENTS = {
    "japan": [122, 153, 20, 46],
    "akita": [139.5, 141.0, 38.8, 40.5],  # 必要に応じて秋田周辺を微調整
    # "tokyo": [...], # 例: 他地域も拡張可
}

# ▼--- データセット安全取得用ヘルパー関数群（省略可） ---▼
def open_isobaric_dataset(fname, hPa=None):
    for ds in cfgrib.open_datasets(fname):
        if "isobaricInhPa" in ds.variables and "step" in ds.dims:
            if hPa is not None:
                if hPa in ds["isobaricInhPa"]:
                    return ds.sel(isobaricInhPa=hPa)
                else:
                    continue
            return ds
    raise RuntimeError(f"[ERROR] isobaricInhPa層データが見つかりません: {fname}")

def open_surface_dataset(fname):
    for ds in cfgrib.open_datasets(fname):
        try:
            if ("stepType" in ds.variables and 
                hasattr(ds, "stepType") and 
                (getattr(ds, "stepType", None) == "instant" or
                 (hasattr(ds.stepType, "values") and 
                  all(ds.stepType.values == "instant")))):
                return ds
        except Exception:
            pass
    try:
        ds = xr.open_dataset(fname, engine="cfgrib", filter_by_keys={"stepType": "instant"})
        return ds
    except Exception:
        pass
    raise RuntimeError(f"[ERROR] 地上instantデータが見つかりません: {fname}")

# ▼--- パネル一括生成・通知本体 ---▼

def generate_universal_panel_and_notify(
    ymd,
    hh,
    model,
    output_dir,
    drive_folder=None,
    ncols=4,
    npages=1,
    nrows=7,
    panel_def=None,    # [(plot_func, ds, title), ...]
    lat_range=None,    # 任意局地
    lon_range=None,
    pin_lat=None,
    pin_lon=None,
    city_name=None,
    slack_channel=None,
    log_callback=None
):
    """
    全国・秋田・任意局地パネル生成＋Zip＋Driveアップ＋Slack通知一括実行
    city_nameに応じて地図範囲を自動切り替え
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")

    # --- 1. データダウンロード ---
    patterns = MODEL_CONFIG.get(model, MODEL_CONFIG["MSM"])["patterns"]
    panel_files = download_gpv_panel(
        patterns, output_dir, dt, GPV_MIRROR_URLS, ncols=ncols*npages
    )
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        log("[ERROR] GPVファイルが見つかりません")
        raise FileNotFoundError("GPVファイルが見つかりません")

    # --- 2. データセット安全取得 ---
    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]
    try:
        ds_isobaric = open_isobaric_dataset(l_pall_fname)
    except Exception as e:
        log(f"[ERROR] isobaricデータ取得失敗: {e}")
        raise
    try:
        ds_surf_instant = open_surface_dataset(lsurf_fname)
    except Exception as e:
        log(f"[ERROR] 地上instantデータ取得失敗: {e}")
        raise

    # --- 3. デフォルトpanel_def（全国用/秋田用/任意局地用など分岐OK） ---
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

    # ▼--- 追加：city_nameによる範囲選択 ---▼
    city_tag = city_name or 'japan'
    extent = REGION_EXTENTS.get(city_tag, REGION_EXTENTS["japan"])

    # --- 4. 画像ページ分割描画 ---
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
                # ▼--- ここで範囲をセット ---▼
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

        page_time_range = f"{ymd} UTC{hh} +{page*ncols*3}h〜+{(page+1)*ncols*3-3}h"
        fig.suptitle(f"{city_tag}天気図パネル（{page_time_range}）", fontsize=20)
        out_name = f"panel_{city_tag}_{ymd}_UTC{hh}_p{page+1}.jpg"
        out_path = os.path.join(output_dir, out_name)
        plt.savefig(out_path, dpi=300)
        plt.close()
        log(f"[OK] 保存: {out_path}")
        panel_imgs.append(out_path)

    # --- 5. ZIP圧縮・Driveアップロード ---
    zip_name = f"panel_{city_tag}_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    log("[STEP3] JPGをZIP圧縮")
    zip_files(panel_imgs, zip_path)
    log(f"[OK] ZIP作成: {zip_path}")

    drive_url = "(未アップロード)"
    if drive_folder:
        log("[STEP4] Google Driveへアップロード")
        delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
        drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
        log(f"[OK] Drive URL: {drive_url}")

    return panel_imgs, zip_path, drive_url
