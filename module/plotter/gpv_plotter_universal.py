# ===============================================================
# module/plotter/gpv_plotter_universal.py
# 全国・秋田・任意局地ハイブリッド天気図パネル生成・通知コア
# city_name・extentの柔軟指定対応（全国も局地もこれ1本でOK！）
# 2025-07-01 ChatGPT
# ===============================================================

import os
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import xarray as xr

from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files

# --- 各変数を個別openするユーティリティ ---
def open_grib2_var_auto(varname, level=None, gsm_path=None, msm_pall_path=None, msm_lsurf_path=None, type_of_level=None, stepType=None):
    """
    変数・層・ファイルパス群から自動で最適ファイルを選び、xarray/cfgribで DataArray または None を返す
    """
    import xarray as xr

    # --- どのファイルを使うか自動判定 ---
    if varname in ["gh", "u", "v", "t", "r"] and level in [300, 500, 700]:
        file_path = gsm_path
    elif varname in ["t", "u", "v", "r"] and level == 850:
        file_path = msm_pall_path
    elif varname == "w" and level == 700:
        file_path = msm_pall_path
    elif varname in ["u10", "v10", "apcp", "prmsl"]:
        file_path = msm_lsurf_path
    else:
        file_path = msm_pall_path  # 何も合致しない場合

    filter_keys = {}
    if type_of_level:
        filter_keys["typeOfLevel"] = type_of_level
    if level is not None:
        if type_of_level == "isobaric":
            filter_keys["isobaricInhPa"] = level
        elif type_of_level == "heightAboveGround":
            filter_keys["level"] = level
    if stepType:
        filter_keys["stepType"] = stepType

    # apcpだけstepType全部トライ
    if varname == "apcp":
        for try_step in ["accum", "avg", "instant"]:
            filter_keys_mod = filter_keys.copy()
            filter_keys_mod["stepType"] = try_step
            try:
                ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys_mod)
                if varname in ds:
                    print(f"[OK] {varname} found with {filter_keys_mod}")
                    return ds[varname]
            except Exception as e:
                continue
        print(f"[WARN] open_grib2_var_auto failed for {varname} (file={file_path}): 全stepTypeトライ失敗")
        return None

    try:
        ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys)
        return ds[varname] if varname in ds else None
    except Exception as e:
        print(f"[WARN] open_grib2_var_auto failed for {varname} (file={file_path}): {e}")
        return None


# --- デバッグ用: 変数一覧ダンプ ---
def dump_grib_vars_auto(file_path, verbose=True):
    """
    GRIB2ファイルで取得可能な全変数・階層・stepType/typeOfLevel組み合わせを列挙
    - まずpygribで全変数ダンプ
    - pygrib未導入なら、cfgribでstepTypeを全部順にサーチ
    """
    try:
        import pygrib
        grbs = pygrib.open(file_path)
        if verbose: print(f"==== pygrib dump: {file_path} ====")
        info = []
        for g in grbs:
            rec = dict(
                name=g.name,
                shortName=g.shortName,
                paramId=g.parameterNumber,
                level=g.level,
                typeOfLevel=g.typeOfLevel,
                stepType=g.stepType if hasattr(g, 'stepType') else None,
            )
            info.append(rec)
            if verbose: print(rec)
        return info
    except ImportError:
        print("[WARN] pygribでのダンプ失敗: No module named 'pygrib'")
    except Exception as e:
        print(f"[WARN] pygribでのダンプ失敗: {e}")

    step_types = ['instant', 'accum', 'avg']
    all_vars = []
    for stepType in step_types:
        try:
            ds = xr.open_dataset(
                file_path, engine="cfgrib", filter_by_keys={"stepType": stepType}
            )
            for v in ds.data_vars:
                da = ds[v]
                rec = dict(
                    name=str(getattr(da, 'long_name', v)),
                    shortName=v,
                    stepType=stepType,
                    dims=str(da.dims),
                    levels=list(da.coords) if hasattr(da, 'coords') else [],
                )
                all_vars.append(rec)
                if verbose:
                    print(f"{v} ({stepType}): dims={da.dims} levels={rec['levels']}")
        except Exception as e:
            if verbose:
                print(f"[WARN] xarray(cfgrib)で stepType={stepType} 失敗: {e}")
    if not all_vars:
        print("Error:  どちらの方法でもGRIB2変数リスト取得に失敗しました。")
    return all_vars

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

    # ここでは全国汎用で取得
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
    panel_def = get_panel_def_japan(panel_datasets)
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

    # 4. ZIP & Drive
    zip_name = f"panel_{city_name}_{ymd}_UTC{hh}.zip"
    zip_path = os.path.join(output_dir, zip_name)
    zip_files(panel_imgs, zip_path)
    drive_url = "(未アップロード)"
    if drive_folder:
        delete_old_files_from_drive(folder_id=drive_folder, older_than_days=30)
        drive_url = upload_to_drive(zip_path, folder_id=drive_folder)
        log(f"[OK] Drive URL: {drive_url}")

    return panel_imgs, zip_path, drive_url
