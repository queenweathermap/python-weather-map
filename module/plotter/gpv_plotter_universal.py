# ===============================================================
# module/plotter/gpv_plotter_universal.py
# 全国・秋田・任意局地ハイブリッド天気図パネル生成・通知コア
# city_name・extentの柔軟指定対応（全国も局地もこれ1本でOK！）
# 湿度fallback（r→q,t派生）・降水量3h差分に対応
# 2025-07-01 ChatGPT
# ===============================================================

import os
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import xarray as xr
import numpy as np

from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files

# --- 湿度fallbackユーティリティ ---
def get_rh_fallback(ds, level_hPa=None):
    """
    ds: xarray.Dataset (cfgrib)
    level_hPa: レベル指定（int, 700/850 など）
    ・rがあればそのまま
    ・なければq,tから計算して返す
    """
    if "r" in ds.variables:
        if level_hPa:
            return ds["r"].sel(isobaricInhPa=level_hPa)
        return ds["r"]
    elif ("q" in ds.variables) and ("t" in ds.variables) and ("isobaricInhPa" in ds.coords):
        try:
            import metpy.calc as mpcalc
            from metpy.units import units
            q = ds["q"].sel(isobaricInhPa=level_hPa) * units("dimensionless")
            t = ds["t"].sel(isobaricInhPa=level_hPa) * units.kelvin
            p = (level_hPa or ds["isobaricInhPa"].values) * units.hectopascal
            # shape揃える（通常: step, lat, lon）
            rh = mpcalc.relative_humidity_from_specific_humidity(q.values, t.values, p)
            rh_da = xr.DataArray(
                rh.magnitude,
                dims=q.dims,
                coords=q.coords,
                name="rh_calc"
            )
            return rh_da
        except Exception as e:
            print(f"[ERROR] RH fallback計算失敗: {e}")
            return None
    else:
        print("[WARN] RH fallback不可")
        return None



# --- 降水量3h差分計算ユーティリティ ---
def get_apcp_3hr(ds):
    """
    ds: xarray.DataArray (apcp, step次元あり)
    MSM積算値しか無い場合は差分で3時間値生成
    """
    if ds is None or "step" not in ds.dims:
        print("[WARN] apcpデータ無効 or step無し")
        return ds
    # shape: (step, lat, lon)
    # 差分（3h前→現在, 0には0をセット）
    apcp_3h = ds.copy()
    apcp_3h.values[1:] = ds.values[1:] - ds.values[:-1]
    apcp_3h.values[0] = np.nan  # 初期値はNaN（必要に応じて0も可）
    apcp_3h.name = "apcp_3hr"
    return apcp_3h
    

# --- 各変数を個別openするユーティリティ ---
def open_grib2_var_auto(
    varname, level=None,
    gsm_path=None, msm_pall_path=None, msm_lsurf_path=None,
    type_of_level=None, stepType=None,
    rh_fallback_func=None, apcp_3hr_func=None,
):
    print(f"\n[DEBUG] open_grib2_var_auto: varname={varname}, level={level}, type_of_level={type_of_level}, stepType={stepType}")

    # --- ファイル自動判定 ---
    if varname in ["gh", "u", "v", "t", "r"] and level in [300, 500, 700]:
        file_path = gsm_path
    elif varname in ["t", "u", "v", "r"] and level == 850:
        file_path = msm_pall_path
    elif varname == "w" and level == 700:
        file_path = msm_pall_path
    elif varname in ["u10", "v10", "apcp", "prmsl"]:
        file_path = msm_lsurf_path
    else:
        file_path = msm_pall_path

    print(f"[DEBUG] open_grib2_var_auto: using file_path={file_path}")
    filter_keys = {}

    # --- 降水量（apcp）は stepType自動切替 ---
    if varname == "apcp":
        for try_step in ["accum", "avg", "instant"]:
            try:
                print(f"[DEBUG] apcp: try stepType={try_step}")
                ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys={"stepType": try_step})
                if varname in ds:
                    print(f"[OK] apcp found with stepType={try_step} shape={ds[varname].shape}")
                    return ds[varname]
            except Exception as e:
                print(f"[WARN] apcp try_step={try_step} failed: {e}")
                continue
        # fallback: 3時間値計算
        if apcp_3hr_func is not None:
            print(f"[WARN] apcp not found. → fallback: get_apcp_3hr()")
            try:
                apcp_3hr = apcp_3hr_func(file_path)
                print(f"[OK] apcp_3hr fallback shape={apcp_3hr.shape}")
                return apcp_3hr
            except Exception as e:
                print(f"[FAIL] apcp_3hr_func failed: {e}")
        print(f"[FAIL] apcp: 全stepType/fallback失敗")
        return None

    # --- 通常変数（stepType自動サーチは不要） ---
    try:
        ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys)
        print(f"[DEBUG] ds.variables: {list(ds.variables.keys())}")
        if varname in ds:
            print(f"[OK] {varname} shape={ds[varname].shape}")
            return ds[varname]
        else:
            print(f"[WARN] {varname} not in ds.variables!")
            # 湿度だけはfallback
            if varname == "r" and rh_fallback_func is not None:
                print(f"[WARN] {varname} fallback: get_rh_fallback()")
                try:
                    rh = rh_fallback_func(ds, level_hPa=level)
                    print(f"[OK] r fallback shape={rh.shape}")
                    return rh
                except Exception as e:
                    print(f"[FAIL] get_rh_fallback failed: {e}")
            return None
    except Exception as e:
        print(f"[FAIL] open_grib2_var_auto: {e}")
        return None


    # --- 通常変数（stepType自動サーチは不要） ---
    try:
        ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys)
        print(f"[DEBUG] ds.variables: {list(ds.variables.keys())}")
        if varname in ds:
            print(f"[OK] {varname} shape={ds[varname].shape}")
            return ds[varname]
        else:
            print(f"[WARN] {varname} not in ds.variables!")
            # 湿度だけはfallback
            if varname == "r" and rh_fallback_func is not None:
                print(f"[WARN] {varname} fallback: get_rh_fallback()")
                try:
                    rh = rh_fallback_func(ds, level_hPa=level)
                    print(f"[OK] r fallback shape={rh.shape}")
                    return rh
                except Exception as e:
                    print(f"[FAIL] get_rh_fallback failed: {e}")
            return None
    except Exception as e:
        print(f"[FAIL] open_grib2_var_auto: {e}")
        return None


# --- パネル生成・通知コア ---
def generate_universal_panel_and_notify(
    ymd, hh,
    gsm_l_pall_path=None,
    msm_l_pall_path=None,
    msm_lsurf_path=None,
    output_dir="./data",
    drive_folder=None,
    ncols=4, npages=1,
    city_name="japan",
    extent=None,
    log_callback=None,
    rh_fallback_func=None,    # ←追加
    apcp_3hr_func=None        # ←追加
):
    """
    全国・秋田・任意パネル生成＋Zip＋Driveアップ一括
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)

    # パネル定義（panel_defは外部で組む運用でも可）
    from module.panel_definitions import get_panel_def_japan
    # ※秋田や任意域ならget_panel_def_akita等に分岐も可能

    # データ収集時print
    print("\n[DEBUG] --- パネル用データ抽出開始 ---")
    panel_datasets = {
        "gh_300": open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "u_300":  open_grib2_var_auto("u", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "v_300":  open_grib2_var_auto("v", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "gh_500": open_grib2_var_auto("gh", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "u_500":  open_grib2_var_auto("u", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "v_500":  open_grib2_var_auto("v", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "t_700":  open_grib2_var_auto("t", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "r_700":  open_grib2_var_auto("r", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "t_500":  open_grib2_var_auto("t", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "t_850":  open_grib2_var_auto("t", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "u_850":  open_grib2_var_auto("u", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "v_850":  open_grib2_var_auto("v", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "w_700":  open_grib2_var_auto("w", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "r_850":  open_grib2_var_auto("r", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
        "prmsl": open_grib2_var_auto("prmsl", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "u10":   open_grib2_var_auto("u10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
        "v10":   open_grib2_var_auto("v10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
        "apcp":  open_grib2_var_auto("apcp", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
    }
    # 収集結果一覧
    print("\n[DEBUG] --- panel_datasets summary ---")
    for k, v in panel_datasets.items():
        if v is None:
            print(f"[WARN] panel_datasets[{k}] = None")
        else:
            print(f"[OK] panel_datasets[{k}] shape={getattr(v, 'shape', 'N/A')} dims={getattr(v, 'dims', 'N/A')}")

    print("\n[DEBUG] --- パネル定義呼び出し ---")
    panel_def = get_panel_def_japan(panel_datasets)
    for i, (func, ds, title) in enumerate(panel_def):
        print(f"[panel_def row {i+1}] {title}  ds: {type(ds)} keys={list(ds.keys()) if isinstance(ds, dict) else ''}")
    nrows = len(panel_def)
    extent = extent or REGION_EXTENTS.get(city_name, REGION_EXTENTS["japan"])

    panel_imgs = []
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=nrows, ncols=ncols,
            figsize=(ncols*3, nrows*3),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )
        for row, (plot_func, ds, title) in enumerate(panel_def):
            # --- DataArray, Datasetの場合だけ step取得 ---
            n_steps = ds.sizes["step"] if (
                ds is not None and hasattr(ds, "sizes") and "step" in ds.sizes
            ) else 0
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

    # ZIP & Google Drive
    zip_name = f"panel_{city_name}_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_files(panel_imgs, zip_path)
    drive_url = "(未アップロード)"
    if drive_folder:
        delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
        drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
        log(f"[OK] Drive URL: {drive_url}")

    return panel_imgs, zip_path, drive_url

# --- パネルグリッド描画汎用関数（panel_utils.py から移動） ---
def make_universal_weather_panel(
    save_dir,
    panel_def,
    times,
    init_time_str,
    city_name="japan",
    ncols=8, nrows=6,   # ←8列6段
    extent=None,
    dpi=300
):
    """
    8列×6段（合計48コマ）の1枚パネル画像を生成
    ファイル右上にイニシャル時刻入りのファイル名
    """
    os.makedirs(save_dir, exist_ok=True)
    panel_imgs = []

    # 行数補完
    if len(panel_def) < nrows:
        for _ in range(nrows - len(panel_def)):
            panel_def.append((None, None, ""))

    fig, axes = plt.subplots(
        nrows=nrows, ncols=ncols,
        figsize=(ncols*3, nrows*3),
        constrained_layout=True,
        subplot_kw=dict(projection=ccrs.PlateCarree())
    )

    for row, (plot_func, ds, title) in enumerate(panel_def):
        n_steps = ds.sizes["step"] if (ds is not None and hasattr(ds, "sizes") and "step" in ds.sizes) else 0
        for col in range(ncols):
            step = col
            ax = axes[row, col]
            if extent:
                ax.set_extent(extent, crs=ccrs.PlateCarree())
            if plot_func is None or ds is None or step >= n_steps:
                ax.axis("off")
                ax.set_title("" if plot_func is None else f"{title} (no data)")
                continue
            try:
                # dictならサイズ確認スキップ（直接プロット関数にstep渡す）
                if isinstance(ds, dict):
                    plot_func(ax, ds, step=step)
                else:
                    ds_step = ds.isel(step=step) if "step" in ds.sizes else ds
                    plot_func(ax, ds_step)
                ax.set_title(f"{title}\n(+{step*3}h)", fontsize=7)
            except Exception as e:
                print(f"[WARN] パネル描画失敗: {title} {e}")
                ax.axis("off")
                ax.set_title(f"{title} (error)", fontsize=7)

    fig.text(0.99, 0.99, f"{city_name}_{init_time_str}", fontsize=10,
             ha="right", va="top", alpha=0.8, color="gray")

    out_name = f"panel_{city_name}_{init_time_str}.jpg"
    out_path = os.path.join(save_dir, out_name)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    panel_imgs.append(out_path)
    return panel_imgs

__all__ = [
    "open_grib2_var_auto",
    "dump_grib_vars_auto",
    "generate_universal_panel_and_notify",
    "make_universal_weather_panel",
    "get_rh_fallback",
    "get_apcp_3hr"
]
