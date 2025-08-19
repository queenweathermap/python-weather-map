# -*- coding: utf-8 -*-
# =============================================================================
# module/plotter/gpv_plotter_universal.py
# -----------------------------------------------------------------------------
# 全国／秋田／任意局地に共通で使える “ユニバーサル” パネル生成コア。
# =============================================================================

from __future__ import annotations

import os
import datetime
from typing import Optional

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from module.panel_definitions import (
    REGION_EXTENTS,
    get_panel_def_japan,
    get_panel_def_akita,
)
from module.utils.zip_utils import zip_files

# ---------------------------------------------------------------------
# cfgrib open の簡易キャッシュ（必要なら利用）
_OPEN_CACHE = {}
def _open_cfgrib_once(path, filter_by_keys):
    key = (path, frozenset((filter_by_keys or {}).items()))
    if key in _OPEN_CACHE:
        return _OPEN_CACHE[key]
    ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys=filter_by_keys or {})
    _OPEN_CACHE[key] = ds
    return ds

# --- Drive 依存を安全に無効化（存在しない場合は no-op 関数に置き換え） ---
try:
    from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
except ImportError:
    def upload_to_drive(*args, **kwargs):
        print("[INFO] Google Drive へのアップロードはスキップされました（no-op）")
        return None
    def delete_old_files_from_drive(*args, **kwargs):
        print("[INFO] Google Drive 上の古いファイル削除はスキップされました（no-op）")
        return None

# =============================================================================
# 相対湿度のフォールバック
# =============================================================================
def get_rh_fallback(ds: xr.Dataset, level_hPa: Optional[int] = None) -> Optional[xr.DataArray]:
    if "r" in ds.variables:
        return ds["r"].sel(isobaricInhPa=level_hPa) if level_hPa else ds["r"]

    if all(k in ds.variables for k in ("q", "t")) and "isobaricInhPa" in ds.coords:
        try:
            import metpy.calc as mpcalc
            from metpy.units import units
            q = ds["q"].sel(isobaricInhPa=level_hPa) if level_hPa else ds["q"]
            t = ds["t"].sel(isobaricInhPa=level_hPa) if level_hPa else ds["t"]
            q_u = (q.values * units.dimensionless)
            t_u = (t.values * units.kelvin)
            p_u = ((level_hPa if level_hPa is not None else ds["isobaricInhPa"].values) * units.hectopascal)
            rh = mpcalc.relative_humidity_from_specific_humidity(q_u, t_u, p_u)
            return xr.DataArray(rh.magnitude, dims=q.dims, coords=q.coords, name="rh_calc",
                                attrs={"long_name": "relative humidity"})
        except Exception as e:
            print(f"[WARN] RH fallback計算失敗: {e}")
            return None

    print("[WARN] RH fallback不可（q,t もしくは座標が不足）")
    return None

# =============================================================================
# 降水量（3時間差分）フォールバック
# =============================================================================
def get_apcp_3hr(file_path: str) -> xr.DataArray:
    last_exc: Optional[Exception] = None
    for step_type in ("accum", "avg", "instant"):
        try:
            ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys={"stepType": step_type})
            key = next((k for k in ("apcp", "APCP", "PRECIP", "precip") if k in ds.variables), None)
            if key is None and "unknown" in ds.variables:
                attrs = ds["unknown"].attrs
                sn = attrs.get("GRIB_shortName", "").lower()
                pn = attrs.get("GRIB_paramName", "").lower()
                if any(x in sn or x in pn for x in ("apcp", "precip")):
                    key = "unknown"
            if key:
                da = ds[key]
                apcp = da.copy()
                apcp.values[1:] = da.values[1:] - da.values[:-1]
                apcp.values[0] = np.nan
                apcp.name = "apcp_3hr"
                return apcp
            last_exc = Exception(f"apcp/precip 系が見つからない stepType={step_type}")
        except Exception as e:
            last_exc = e
            print(f"[WARN] get_apcp_3hr: stepType={step_type} open failed: {e}")
    raise last_exc if last_exc else RuntimeError("get_apcp_3hr: 不明なエラー")

# =============================================================================
# 変数ユニバーサルオープナ
# =============================================================================
def open_grib2_var_auto(
    varname, level=None,
    gsm_path=None, msm_pall_path=None, msm_lsurf_path=None,
    type_of_level=None, stepType=None,
    rh_fallback_func=None, apcp_3hr_func=None,
):
    # 等圧面系は MSM L-pall、地上風/海面気圧/降水は Lsurf
    if varname in ["gh", "u", "v", "t", "r", "w"]:
        file_path = msm_pall_path
    elif varname in ["u10", "v10", "prmsl", "apcp"]:
        file_path = msm_lsurf_path
    else:
        file_path = msm_pall_path

    filter_keys = {}
    if varname in ["gh", "u", "v", "t", "r", "w"]:
        filter_keys = {"typeOfLevel": "isobaricInhPa", "level": level}
    elif varname in ["u10", "v10"]:
        filter_keys = {"typeOfLevel": "heightAboveGround", "level": 10, "stepType": "instant"}
    elif varname == "prmsl":
        filter_keys = {"typeOfLevel": "meanSea", "stepType": "instant"}

    try:
        ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys)
        if varname in ds:
            return ds[varname]

        if varname == "r" and rh_fallback_func is not None:
            rh = rh_fallback_func(ds, level_hPa=level)
            if rh is not None:
                return rh

        if varname == "apcp" and apcp_3hr_func is not None and msm_lsurf_path:
            return apcp_3hr_func(msm_lsurf_path)

        return None
    except Exception as e:
        if varname == "apcp" and apcp_3hr_func is not None and msm_lsurf_path:
            try:
                return apcp_3hr_func(msm_lsurf_path)
            except Exception:
                pass
        print(f"[FAIL] open_grib2_var_auto: file={file_path}, filter={filter_keys}, err={e}")
        return None

# =============================================================================
# まとめ生成（Drive は任意）
# =============================================================================
def generate_universal_panel_and_notify(
    ymd: str,
    hh: str,
    *,
    gsm_l_pall_path: Optional[str] = None,
    msm_l_pall_path: Optional[str] = None,
    msm_lsurf_path: Optional[str] = None,
    output_dir: str = "./data",
    drive_folder: Optional[str] = None,
    ncols: int = 3,
    npages: int = 3,
    city_name: str = "japan",
    extent: Optional[list[float]] = None,
    log_callback=None,
    rh_fallback_func=get_rh_fallback,
    apcp_3hr_func=get_apcp_3hr,
):
    """
    全国・秋田・任意パネル生成 → Zip → （任意で）Drive アップロード。
    戻り値: (panel_imgs: list[str], zip_path: str, drive_url: str)
    """
    def log(msg: str):
        print(msg)
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    os.makedirs(output_dir, exist_ok=True)

    # --- データ抽出 -----------------------------------------------------------
    print("\n[DEBUG] --- パネル用データ抽出開始 ---")
    panel_datasets = {
        "gh_300": open_grib2_var_auto("gh", 300, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path, rh_fallback_func=rh_fallback_func),
        "u_300":  open_grib2_var_auto("u", 300, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "v_300":  open_grib2_var_auto("v", 300, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),

        "gh_500": open_grib2_var_auto("gh", 500, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "u_500":  open_grib2_var_auto("u", 500, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "v_500":  open_grib2_var_auto("v", 500, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),

        "t_700":  open_grib2_var_auto("t", 700, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "r_700":  open_grib2_var_auto("r", 700, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path, rh_fallback_func=rh_fallback_func),

        "t_500":  open_grib2_var_auto("t", 500, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),

        "t_850":  open_grib2_var_auto("t", 850, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "u_850":  open_grib2_var_auto("u", 850, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "v_850":  open_grib2_var_auto("v", 850, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),

        "w_700":  open_grib2_var_auto("w", 700, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),

        "r_850":  open_grib2_var_auto("r", 850, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path, rh_fallback_func=rh_fallback_func),

        "u10":    open_grib2_var_auto("u10", 10, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "v10":    open_grib2_var_auto("v10", 10, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "apcp":   open_grib2_var_auto("apcp", None, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path, apcp_3hr_func=apcp_3hr_func),
        "prmsl":  open_grib2_var_auto("prmsl", None, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),

        # 必要に応じて 925/975 を有効化
        "t_925": open_grib2_var_auto("t", 925, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "u_925": open_grib2_var_auto("u", 925, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "v_925": open_grib2_var_auto("v", 925, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "r_925": open_grib2_var_auto("r", 925, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path, rh_fallback_func=rh_fallback_func),
        "t_975": open_grib2_var_auto("t", 975, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "u_975": open_grib2_var_auto("u", 975, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "v_975": open_grib2_var_auto("v", 975, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path),
        "r_975": open_grib2_var_auto("r", 975, msm_pall_path=msm_l_pall_path, msm_lsurf_path=msm_lsurf_path, rh_fallback_func=rh_fallback_func),
    }

    print("\n[DEBUG] --- panel_datasets summary ---")
    for k, v in panel_datasets.items():
        if v is None:
            print(f"[WARN] {k}: None")
        else:
            print(f"[OK] {k}: shape={getattr(v, 'shape', None)} dims={getattr(v, 'dims', None)}")

    # --- パネル定義（地域別に選択） -------------------------------------------
    print("\n[DEBUG] --- パネル定義呼び出し ---")
    if city_name.lower() == "akita":
        panel_def = get_panel_def_akita(panel_datasets)
    else:
        panel_def = get_panel_def_japan(panel_datasets)

    nrows = len(panel_def)
    extent = extent or REGION_EXTENTS.get(city_name, REGION_EXTENTS["japan"])

    PANEL_FIGSIZE_UNIT = 2.0
    PANEL_DPI = 200

    panel_imgs: list[str] = []
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=nrows,
            ncols=ncols,
            figsize=(ncols * PANEL_FIGSIZE_UNIT, nrows * PANEL_FIGSIZE_UNIT),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree()),
        )

        for row, (plot_func, ds, title) in enumerate(panel_def):
            # dict でも step 数を推定
            if isinstance(ds, dict):
                any_da = next((v for v in ds.values() if v is not None), None)
                n_steps = (any_da.sizes["step"]
                           if (any_da is not None and hasattr(any_da, "sizes") and "step" in any_da.sizes)
                           else 0)
            else:
                n_steps = (ds.sizes["step"]
                           if (ds is not None and hasattr(ds, "sizes") and "step" in ds.sizes)
                           else 0)

            for col in range(ncols):
                step = page * ncols + col
                ax = axes[row, col]
                if extent:
                    ax.set_extent(extent, crs=ccrs.PlateCarree())

                if (plot_func is None) or (ds is None) or (step >= n_steps):
                    ax.axis("off")
                    ax.set_title("" if plot_func is None else f"{title} (no data)", fontsize=7)
                    continue

                try:
                    plot_func(ax, ds, step=step)
                    ax.set_title(f"{title}\n(+{step*3}h)", fontsize=7)
                except Exception as e:
                    print(f"[WARN] パネル描画失敗: {title} step={step} :: {e}")
                    ax.axis("off")
                    ax.set_title(f"{title} (error)", fontsize=7)

        fig.suptitle(f"{city_name} 天気図パネル（{ymd} UTC{hh}） p{page+1}", fontsize=14)
        out_name = f"panel_{city_name}_{ymd}_UTC{hh}_p{page+1}.jpg"
        out_path = os.path.join(output_dir, out_name)
        fig.savefig(out_path, dpi=PANEL_DPI)
        plt.close(fig)
        log(f"[OK] 保存: {out_path}")
        panel_imgs.append(out_path)

    # --- Zip & Drive（任意） ---------------------------------------------------
    zip_name = f"panel_{city_name}_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_files(panel_imgs, zip_path)

    drive_url = "未アップロード"
    if drive_folder:
        try:
            delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
        except Exception as e:
            print(f"[WARN] Drive cleanup skipped: {e}")
        try:
            drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
            log(f"[OK] Drive URL: {drive_url}")
        except Exception as e:
            print(f"[WARN] Drive upload failed: {e}")

    return panel_imgs, zip_path, drive_url

# =============================================================================
# 1枚パネル（横に時刻を並べる or 単一 step を 1 枚だけ）
# =============================================================================
def make_universal_weather_panel(
    save_dir: str,
    panel_def: list,
    times,  # 互換のため残す（未使用）
    init_time_str: str,
    *,
    city_name: str = "japan",
    ncols: int = 16,
    nrows: int = 6,
    extent: Optional[list[float]] = None,
    dpi: int = 300,
    step: Optional[int] = None,
):
    os.makedirs(save_dir, exist_ok=True)
    panel_imgs: list[str] = []

    if len(panel_def) < nrows:
        panel_def = panel_def + [(None, None, "")] * (nrows - len(panel_def))

    PANEL_FIGSIZE_UNIT = 2.0  # この関数内でも使う
    fig, axes = plt.subplots(
        nrows=nrows, ncols=ncols,
        figsize=(ncols * PANEL_FIGSIZE_UNIT, nrows * PANEL_FIGSIZE_UNIT),
        constrained_layout=True,
        subplot_kw=dict(projection=ccrs.PlateCarree()),
    )
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1:
        axes = axes[np.newaxis, :]
    elif ncols == 1:
        axes = axes[:, np.newaxis]

    for row, (plot_func, ds, title) in enumerate(panel_def):
        if isinstance(ds, dict):
            arr = next((v for v in ds.values() if v is not None), None)
            n_steps = (arr.sizes["step"] if (arr is not None and "step" in getattr(arr, "sizes", {})) else 0)
        else:
            n_steps = (ds.sizes["step"] if (ds is not None and "step" in getattr(ds, "sizes", {})) else 0)

        step_indices = [step] if step is not None else range(ncols)
        for idx, col in enumerate(step_indices):
            ax = axes[row, idx]
            if extent:
                ax.set_extent(extent, crs=ccrs.PlateCarree())

            if (plot_func is None) or (ds is None) or (col >= n_steps):
                ax.axis("off")
                ax.set_title("" if plot_func is None else f"{title} (no data)")
                continue

            try:
                if isinstance(ds, dict):
                    plot_func(ax, ds, step=col)
                else:
                    plot_func(ax, ds.isel(step=col))
                ax.set_title(f"{title} (+{col*3}h)")
            except Exception as e:
                print(f"[WARN] make_universal_weather_panel: {title} col={col} :: {e}")
                ax.axis("off")
                ax.set_title(f"{title} (error)")

    ymd = init_time_str[:8]
    hh = init_time_str[-2:]
    base_dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")
    if step is not None:
        t = base_dt + datetime.timedelta(hours=step * 3)
        fig.text(0.5, 0.01, t.strftime("%Y%m%d %HUTC"), ha="center", va="bottom", fontsize=11, color="gray", alpha=0.95)
    else:
        for col in range(ncols):
            t = base_dt + datetime.timedelta(hours=col * 3)
            x = (col + 0.5) / ncols
            fig.text(x, 0.01, t.strftime("%Y%m%d %HUTC"), ha="center", va="bottom", fontsize=11, color="gray", alpha=0.95)

    out_path = os.path.join(save_dir, f"panel_{city_name}_{init_time_str}_p1.jpg")
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    panel_imgs.append(out_path)
    return panel_imgs

# =============================================================================
# デバッグ用：そのファイルで参照可能な cfgrib 変数をざっと列挙
# =============================================================================
def dump_grib_vars_auto(file_path: str) -> None:
    combos = [
        {"typeOfLevel": "isobaricInhPa", "level": 850},
        {"typeOfLevel": "isobaricInhPa", "level": 700},
        {"typeOfLevel": "isobaricInhPa", "level": 500},
        {"typeOfLevel": "heightAboveGround", "level": 10, "stepType": "instant"},
        {"typeOfLevel": "meanSea", "stepType": "instant"},
        {"stepType": "accum"}, {"stepType": "avg"}, {"stepType": "instant"},
    ]
    for fk in combos:
        try:
            ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=fk)
            print(f"[DEBUG] vars for {fk}: {list(ds.variables)}")
        except Exception as e:
            print(f"[DEBUG] open failed for {fk}: {e}")

__all__ = [
    "open_grib2_var_auto",
    "generate_universal_panel_and_notify",
    "make_universal_weather_panel",
    "get_rh_fallback",
    "get_apcp_3hr",
    "dump_grib_vars_auto",
]
