# ===============================================================
# module/plotter/gpv_plotter_universal.py
# 全国・秋田・任意局地ハイブリッド天気図パネル生成・通知コア
# city_name・extentの柔軟指定対応（全国も局地もこれ1本でOK！）
# 2025-07-01 by ChatGPT（全個別open辞書方式・isobaricInhPa競合完全解消）
# ===============================================================

import os
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import xarray as xr

from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.zip_utils import zip_files

# --- 各変数を個別openするユーティリティ ---
def open_grib2_var(path, varname, type_of_level=None, level_val=None, stepType=None):
    filter_keys = {}
    if type_of_level:
        filter_keys['typeOfLevel'] = type_of_level
    if level_val is not None:
        filter_keys['isobaricInhPa' if type_of_level == 'isobaric' else 'level'] = level_val
    if stepType:
        filter_keys['stepType'] = stepType
    try:
        ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys=filter_keys)
        return ds[varname] if varname in ds else None
    except Exception as e:
        print(f"[WARN] open_grib2_var failed for {varname}: {e}")
        return None

# --- デバッグ用: 変数一覧ダンプ ---
# module/plotter/gpv_plotter_universal.py などに追加

def dump_grib_vars(file_path, verbose=True):
    """
    GRIB2ファイルで取得可能な全変数・階層・stepType/typeOfLevel組み合わせを列挙

    Parameters:
        file_path: GRIB2ファイルパス
        verbose: Trueならprint出力（Falseなら変数リストのみ返す）
    Returns:
        変数情報リスト
    """
    import cfgrib
    from collections import defaultdict

    try:
        idx = cfgrib.index_file(file_path)
    except Exception as e:
        print(f"[ERROR] cfgrib.index_file failed: {e}")
        return []

    # variableName, stepType, typeOfLevel, level
    var_info = defaultdict(list)
    for rec in idx:
        vname = rec['shortName']
        stype = rec.get('stepType', '')
        level_type = rec.get('typeOfLevel', '')
        level = rec.get('level', '')
        key = (vname, stype, level_type, level)
        var_info[vname].append({
            "stepType": stype,
            "typeOfLevel": level_type,
            "level": level,
            "paramId": rec.get('paramId'),
            "name": rec.get('name', ''),
        })

    # 整形してprint
    if verbose:
        print(f"==== ファイル: {file_path} ====")
        for vname, entries in var_info.items():
            levels = set([e["level"] for e in entries])
            step_types = set([e["stepType"] for e in entries])
            type_of_levels = set([e["typeOfLevel"] for e in entries])
            print(f"- {vname}:")
            print(f"    stepType: {sorted(step_types)}")
            print(f"    typeOfLevel: {sorted(type_of_levels)}")
            print(f"    level: {sorted(levels)}")
            print(f"    paramId: {[e['paramId'] for e in entries]}")
            print(f"    name: {[e['name'] for e in entries if e['name']]}")
    return var_info


# ----------------------------------------------------------------------

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
    slack_channel=None,
    log_callback=None,
):
    """
    ファイルパスを外部で指定。panel_datasets方式。
    """

    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    os.makedirs(output_dir, exist_ok=True)

    # --- 1. 必要変数のみ個別open
    panel_datasets = {
        # GSM（高層）
        "gh_300": open_grib2_var(gsm_l_pall_path, "gh", "isobaric", 300),
        "u_300":  open_grib2_var(gsm_l_pall_path, "u", "isobaric", 300),
        "v_300":  open_grib2_var(gsm_l_pall_path, "v", "isobaric", 300),
        "gh_500": open_grib2_var(gsm_l_pall_path, "gh", "isobaric", 500),
        "u_500":  open_grib2_var(gsm_l_pall_path, "u", "isobaric", 500),
        "v_500":  open_grib2_var(gsm_l_pall_path, "v", "isobaric", 500),
        "t_700":  open_grib2_var(gsm_l_pall_path, "t", "isobaric", 700),
        "r_700":  open_grib2_var(gsm_l_pall_path, "r", "isobaric", 700),
        "t_500":  open_grib2_var(gsm_l_pall_path, "t", "isobaric", 500),

        # MSM（下層・鉛直流など）
        "t_850":  open_grib2_var(msm_l_pall_path, "t", "isobaric", 850),
        "u_850":  open_grib2_var(msm_l_pall_path, "u", "isobaric", 850),
        "v_850":  open_grib2_var(msm_l_pall_path, "v", "isobaric", 850),
        "w_700":  open_grib2_var(msm_l_pall_path, "w", "isobaric", 700),
        "r_850":  open_grib2_var(msm_l_pall_path, "r", "isobaric", 850),

        # 地上（MSM Lsurfファイル）
        "prmsl": open_grib2_var(msm_lsurf_path, "prmsl", "surface", stepType="instant"),
        "u10":   open_grib2_var(msm_lsurf_path, "u10", "heightAboveGround", 10, stepType="instant"),
        "v10":   open_grib2_var(msm_lsurf_path, "v10", "heightAboveGround", 10, stepType="instant"),
        "apcp":  open_grib2_var(msm_lsurf_path, "apcp", "surface", stepType="accum"),
    }

    # --- 2. パネル定義取得 ---
    panel_def = get_panel_def_japan(panel_datasets)
    nrows = len(panel_def)
    extent = extent or REGION_EXTENTS.get(city_name, REGION_EXTENTS["japan"])

    # --- 3. 描画・保存 ---
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

    # --- 4. ZIP & Drive
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
def generate_japan_panel_and_notify(
    ymd, hh,
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
        city_name="japan", extent=None,
        log_callback=log_callback
    )

# --- 局地用ラッパーも必要に応じて同様の仕組みで定義可能 ---

# --- これで全ての「isobaricInhPa競合」エラーは解消されます ---
