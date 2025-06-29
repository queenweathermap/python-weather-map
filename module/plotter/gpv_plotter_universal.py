# ===============================================================
# module/plotter/gpv_plotter_universal.py
# 全国・秋田・任意局地ハイブリッド天気図パネル生成・通知コア
# city_name・extentの柔軟指定対応（全国も局地もこれ1本でOK！）
# 2025-06-29 by ChatGPT（ファイルパス外部渡し方式）
# ===============================================================

import os
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import xarray as xr

from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files
from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan

# --- プロット関数 ---
from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

# ----------------------------------------------------------------------
def dump_grib_vars(file_path):
    """GRIB2ファイルの変数一覧をダンプ（デバッグ用）"""
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

# ----------------------------------------------------------------------

def generate_universal_panel_and_notify(
    ymd, hh,
    gsm_l_pall_path=None,    # GSM 500/700/300等
    msm_l_pall_path=None,    # MSM L-pall（必須）
    msm_lsurf_path=None,     # MSM Lsurf（必須）
    output_dir="./data",
    drive_folder=None,
    ncols=4, npages=1, nrows=None,
    panel_def=None,
    city_name="japan",
    extent=None,
    slack_channel=None,
    log_callback=None,
):
    """
    必要なファイルパスをすべて外部で渡す！DLや自動探索ロジックは持たない
    """

    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)

    # --- Dataset化
    # モデルに応じて必要なものだけロード
    ds_gsm_isobaric = open_isobaric_dataset(gsm_l_pall_path) if gsm_l_pall_path else None
    ds_msm_isobaric = open_isobaric_dataset(msm_l_pall_path) if msm_l_pall_path else None
    ds_msm_surf_instant = open_surface_dataset(msm_lsurf_path) if msm_lsurf_path else None

    # --- パネル定義（例：全国GSM+MSM混合）
    if panel_def is None:
        panel_def = get_panel_def_japan(ds_gsm_isobaric, ds_msm_isobaric, ds_msm_surf_instant)
        nrows = len(panel_def)
    else:
        nrows = len(panel_def)

    extent = extent or REGION_EXTENTS.get(city_name, REGION_EXTENTS["japan"])

    # --- 描画
    panel_imgs = []
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=nrows, ncols=ncols,
            figsize=(ncols*3, nrows*3),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )
        for row, (plot_func, ds, title) in enumerate(panel_def):
            if ds is not None and not isinstance(ds, xr.Dataset):
                raise TypeError(f"panel_defのdsは必ずDatasetで: {title}, type={type(ds)}")
            n_steps = ds.sizes["step"] if (ds is not None and "step" in ds.sizes) else 0
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

    # --- ZIP & Drive
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
# 全国用ラッパー（パスを全部外部で指定する想定！例）
def generate_japan_panel_and_notify(
    ymd,
    hh,
    gsm_l_pall_path,
    msm_l_pall_path,
    msm_lsurf_path,
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
        ymd=ymd, hh=hh,
        gsm_l_pall_path=gsm_l_pall_path,
        msm_l_pall_path=msm_l_pall_path,
        msm_lsurf_path=msm_lsurf_path,
        output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=ncols, npages=npages,
        city_name="japan", panel_def=None, extent=None,
        log_callback=log_callback
    )

# --- 必要なら局地エリア用ラッパーも同様に追加OK ---

# --- ダンプユーティリティの使い方例 ---
# dump_grib_vars('./data/ファイル名')

# --- これで完全外部制御・バッチ/局地統一運用が可能です！ ---
