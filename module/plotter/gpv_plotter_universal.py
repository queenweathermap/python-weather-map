# module/plotter/gpv_plotter_universal.py
# ===============================================================
# 全国・秋田・任意局地ハイブリッド天気図パネル生成・通知コア
# city_name・extentの柔軟指定対応（全国も局地もこれ1本でOK！）
# 2025-06-28 by ChatGPT（統合版・整理済み）
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
from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan  # 必要に応じ他エリアもimport

# --- プロット関数 ---
from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

# -----------------------------------------------
# ファイルパス例
file_path = "./data/Z__C_RJTD_20250626000000_GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin"
if not os.path.exists(file_path):
    print("[ERROR] ファイルがありません:", file_path)
    print("data/ディレクトリの中身:", os.listdir("./data"))
    raise FileNotFoundError(file_path)

# cfgrib.open_datasetsで分割された各サブセット（filter_by_keysごと）をすべて確認
datasets = cfgrib.open_datasets(file_path)
print(f"全{len(datasets)}サブセット")

for i, ds in enumerate(datasets):
    print(f"\n--- Dataset #{i+1} ---")
    print("Variables:", list(ds.data_vars))
    print("Coords:", list(ds.coords))
    print("Attrs:", ds.attrs)
    # 詳細を表示したい場合は
    for var in ds.data_vars:
        print(f"\n  [{var}]")
        print(ds[var])
        print("    coords:", ds[var].coords)
        print("    attrs :", ds[var].attrs)



# ★ 変数一覧ダンプユーティリティ（必要な時だけ使う）★
def dump_grib_vars(file_path):
    print(f"\n==== ファイル: {file_path} ====")
    for step in ["instant", "accum", "avg"]:
        try:
            ds = xr.open_dataset(
                file_path,
                engine="cfgrib",
                backend_kwargs={'filter_by_keys': {'stepType': step}}
            )
            print(f"\n[{step}] 変数:", list(ds.data_vars))
        except Exception as e:
            print(f"[{step}] 読み込み不可: {e}")
# -----------------------------------------------

def generate_universal_panel_and_notify(
    ymd, hh, model, output_dir,
    drive_folder=None,
    ncols=4, npages=1, nrows=None,
    panel_def=None,
    city_name="japan",
    extent=None,    # 任意範囲も直接指定OK
    slack_channel=None,
    log_callback=None,
):
    """
    全国・局地どちらも city_name/panel_def/extent で切替。
    必要なら外部でget_panel_def_xxx, REGION_EXTENTS等を定義して呼び出す。
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")

    # --- データDL ---
    patterns = MODEL_CONFIG.get(model, MODEL_CONFIG["MSM"])["patterns"]
    panel_files = download_gpv_panel(patterns, output_dir, dt, GPV_MIRROR_URLS, ncols=ncols*npages)
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        log("[ERROR] GPVファイルが見つかりません")
        raise FileNotFoundError("GPVファイルが見つかりません")

    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]
    ds_isobaric = open_isobaric_dataset(l_pall_fname)
    ds_surf_instant = open_surface_dataset(lsurf_fname)

    # --- パネル定義 ---
    if panel_def is None:
        # 全国デフォルト
        panel_def = get_panel_def_japan(ds_isobaric, ds_surf_instant)
        nrows = len(panel_def)
    else:
        nrows = len(panel_def)

    # --- 範囲（全国・局地…） ---
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

# -----------------------------------------------
# （例）全国用ラッパー　※局地用も同様にwrapperを作るだけ！
def generate_japan_panel_and_notify(
    ymd,
    hh,
    model="HYBRID",
    output_dir="./data",
    drive_folder=None,
    ncols=4,
    npages=4,
    log_callback=None,
):
    """
    全国パネル生成＋Zip＋Driveアップ一括実行
    """
    return generate_universal_panel_and_notify(
        ymd=ymd, hh=hh, model=model, output_dir=output_dir,
        drive_folder=drive_folder, ncols=ncols, npages=npages,
        city_name="japan", panel_def=None, extent=None,
        log_callback=log_callback
    )

# -----------------------------------------------

# --- 必要なら局地エリア版ラッパーを追加でOK ---
# def generate_local_panel_and_notify(...):  # panel_def/extentだけ局地用に

# --- ダンプユーティリティの使い方例 ---
# dump_grib_vars('./data/ファイル名')

# --- これで完全集約できます！ ---
