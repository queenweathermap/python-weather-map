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
from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan  # 必要に応じて他エリアのgetterもimport


file_path = "（例）./data/Z__C_RJTD_20250627000000_MSM_GPV_Rjp_L-pall_FH00-15_grib2.nc"

# cfgribエンジンで読み込み
ds = xr.open_dataset(file_path, engine="cfgrib")

print("\n[変数名一覧]")
print(list(ds.data_vars))

for var in ds.data_vars:
    print(f"\n=== {var} ===")
    print(ds[var])
    print("coords:", ds[var].coords)
    print("attrs :", ds[var].attrs)

print("\n[座標軸一覧]")
print(ds.coords)



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
    panel_defは外部（panel_definitions.py）から渡す運用推奨。
    指定がなければ全国デフォルトpanel_defを適用。
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")

    # --- データダウンロード ---
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
        # デフォルトは全国用
        panel_def = get_panel_def_japan(ds_isobaric, ds_surf_instant)
        nrows = len(panel_def)
    else:
        nrows = len(panel_def)

    # --- 範囲選択 ---
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
            # step数判定（空欄マスはds=Noneなのでn_steps=0）
            n_steps = ds.dims["step"] if (ds is not None and "step" in ds.dims) else 0
            for col in range(ncols):
                step = page * ncols + col
                ax = axes[row, col]
                ax.set_extent(extent, crs=ccrs.PlateCarree())
                if plot_func is None or ds is None or step >= n_steps:
                    ax.axis("off")
                    ax.set_title("" if plot_func is None else f"{title} (no data)")
                    continue
                try:
                    ds_step = ds.isel(step=step)
                    plot_func(ax, ds_step)
                    ax.set_title(f"{title} (+{step*3}h)")
                except Exception as e:
                    ax.axis("off")
                    ax.set_title(f"{title} (エラー)")
                    log(f"[ERROR] {title}: {e}")
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
