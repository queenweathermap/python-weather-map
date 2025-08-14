# -*- coding: utf-8 -*-
# =============================================================================
# module/plotter/gpv_plotter_universal.py
# -----------------------------------------------------------------------------
# 全国／秋田／任意局地に共通で使える “ユニバーサル” パネル生成コア。
#
# 特色
#  - 変数ごとに cfgrib を安全に open（欠損はフォールバックで緩やかに継続）
#  - 相対湿度 r が無いときは q,t から計算（MetPy 利用）
#  - 降水量 apcp が無いときは “累積→3h差分” を自動生成
#  - ncols×nrows の柔軟なグリッド描画（全国も局地も1本でOK）
#  - Drive を使わない運用に対応：import できなければ自動で no-op にフォールバック
#
# 想定呼び出し
#  - open_grib2_var_auto(...) で個別変数を取り出し
#  - generate_universal_panel_and_notify(...) でまとめて生成（Drive は任意）
#  - make_universal_weather_panel(...) で 1 枚パネル（時刻横並び or 単一 step）
#
# 依存（このモジュール外）
#  - module.panel_definitions: REGION_EXTENTS, get_panel_def_japan（ほか各 get_panel_def_*）
#  - module.utils.zip_utils: zip_files
#
# 2025-08 改訂（Drive 依存を no-op に、ログを強化）
# =============================================================================

from __future__ import annotations

import os
import datetime
from typing import Optional, Dict, Any

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan
from module.utils.zip_utils import zip_files


# --- Drive 依存を安全に無効化（存在しない場合は no-op 関数に置き換え） ---
try:
    from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
except ImportError:
    def upload_to_drive(*args, **kwargs):
        """Driveが利用できない場合の代替（処理なし）"""
        print("[INFO] Google Drive へのアップロードはスキップされました（no-op）")
        return None

    def delete_old_files_from_drive(*args, **kwargs):
        """Driveが利用できない場合の代替（処理なし）"""
        print("[INFO] Google Drive 上の古いファイル削除はスキップされました（no-op）")
        return None


# =============================================================================
# 相対湿度のフォールバック
# =============================================================================
def get_rh_fallback(ds: xr.Dataset, level_hPa: Optional[int] = None) -> Optional[xr.DataArray]:
    """
    r が無いとき、q と t（必要なら p）から相対湿度を計算して返す。
    - ds: cfgrib で開いた Dataset
    - level_hPa: isobaric 層（例: 700, 850）
    戻り値: xr.DataArray (dims は q に合わせる) / 失敗時 None
    """
    # r があればそのまま
    if "r" in ds.variables:
        return ds["r"].sel(isobaricInhPa=level_hPa) if level_hPa else ds["r"]

    # q, t があれば計算
    if all(k in ds.variables for k in ("q", "t")) and "isobaricInhPa" in ds.coords:
        try:
            import metpy.calc as mpcalc
            from metpy.units import units

            q = ds["q"].sel(isobaricInhPa=level_hPa) if level_hPa else ds["q"]
            t = ds["t"].sel(isobaricInhPa=level_hPa) if level_hPa else ds["t"]

            q_u = (q.values * units("dimensionless"))
            t_u = (t.values * units.kelvin)

            # level 指定時はスカラー、未指定時は座標全体
            p_u = ((level_hPa if level_hPa is not None else ds["isobaricInhPa"].values) * units.hectopascal)

            rh = mpcalc.relative_humidity_from_specific_humidity(q_u, t_u, p_u)
            rh_da = xr.DataArray(
                rh.magnitude, dims=q.dims, coords=q.coords, name="rh_calc", attrs={"long_name": "relative humidity"}
            )
            return rh_da
        except Exception as e:
            print(f"[WARN] RH fallback計算失敗: {e}")
            return None

    print("[WARN] RH fallback不可（q,t もしくは座標が不足）")
    return None


# =============================================================================
# 降水量（3時間差分）フォールバック
# =============================================================================
def get_apcp_3hr(file_path: str) -> xr.DataArray:
    """
    apcp が見つからない場合に、同一ファイル内の累積降水等から 3h 差分を作る。
    見つけやすい stepType を順に試す。
    """
    last_exc: Optional[Exception] = None
    for step_type in ("accum", "avg", "instant"):
        try:
            ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys={"stepType": step_type})
            print(f"[DEBUG] get_apcp_3hr: stepType={step_type}, vars={list(ds.variables)}")

            # 候補名で探索
            key = next((k for k in ("apcp", "APCP", "PRECIP", "precip") if k in ds.variables), None)

            # unknown に paramName が入るケースの救済
            if key is None and "unknown" in ds.variables:
                attrs = ds["unknown"].attrs
                sn = attrs.get("GRIB_shortName", "").lower()
                pn = attrs.get("GRIB_paramName", "").lower()
                if any(x in sn or x in pn for x in ("apcp", "precip")):
                    key = "unknown"

            if key:
                da = ds[key]
                apcp = da.copy()
                # 3h 差分（先頭は NaN）
                apcp.values[1:] = da.values[1:] - da.values[:-1]
                apcp.values[0] = np.nan
                apcp.name = "apcp_3hr"
                return apcp

            last_exc = Exception(f"apcp/precip 系の変数が見つからない stepType={step_type}")

        except Exception as e:
            print(f"[WARN] get_apcp_3hr: stepType={step_type} open failed: {e}")
            last_exc = e

    raise last_exc if last_exc else RuntimeError("get_apcp_3hr: 不明なエラー")


# =============================================================================
# 変数ユニバーサルオープナ
# =============================================================================
def open_grib2_var_auto(
    varname: str,
    level: Optional[int] = None,
    gsm_path: Optional[str] = None,
    msm_pall_path: Optional[str] = None,
    msm_lsurf_path: Optional[str] = None,
    type_of_level: Optional[str] = None,  # 互換のため残す（自動で決める）
    stepType: Optional[str] = None,
    rh_fallback_func=get_rh_fallback,
    apcp_3hr_func=get_apcp_3hr,
):
    """
    変数名から自動で “どのファイルをどの filter_by_keys で開くか” を決めて返す。
    見つからない／開けない場合は None を返す。
    """
    print(f"\n[DEBUG] open_grib2_var_auto: var={varname}, level={level}, stepType={stepType}")

    # --- ファイル自動判定（経験則ベース） ---
    if varname in ("gh", "u", "v", "t", "r"):
        file_path = gsm_path if (level in (300, 500, 700)) else msm_pall_path
    elif varname == "w":
        file_path = msm_pall_path
    elif varname in ("u10", "v10", "prmsl", "apcp"):
        file_path = msm_lsurf_path
    else:
        file_path = msm_pall_path

    if not file_path:
        print(f"[WARN] open_grib2_var_auto: file_path 未指定（var={varname}）")
        return None

    # --- filter_by_keys 構築 ---
    fkeys: Dict[str, Any] = {}
    if varname in ("gh", "u", "v", "t", "r", "w"):
        fkeys = {"typeOfLevel": "isobaricInhPa", "level": level}
    elif varname in ("u10", "v10"):
        fkeys = {"typeOfLevel": "heightAboveGround", "level": 10, "stepType": "instant"}
    elif varname == "prmsl":
        fkeys = {"typeOfLevel": "meanSea", "stepType": "instant"}
    elif varname == "apcp":
        # apcp は stepType が揺れるため後段で特別処理する
        pass

    print(f"[DEBUG] open_grib2_var_auto: use file={file_path}, filter={fkeys or '(apcp special)'}")

    # --- apcp の特別処理（順に試す→fallback で 3h 差分） ---
    if varname == "apcp":
        for try_step in ("accum", "avg", "instant"):
            try:
                ds = xr.open_dataset(
                    file_path, engine="cfgrib", filter_by_keys={"typeOfLevel": "surface", "stepType": try_step}
                )
                if "apcp" in ds:
                    print(f"[OK] apcp found stepType={try_step} shape={ds['apcp'].shape}")
                    return ds["apcp"]
            except Exception as e:
                print(f"[WARN] apcp open (stepType={try_step}) failed: {e}")

        # fallback: 3h 差分
        try:
            ap = apcp_3hr_func(file_path) if apcp_3hr_func else None
            if ap is not None:
                print(f"[OK] apcp_3hr fallback shape={ap.shape}")
                return ap
        except Exception as e:
            print(f"[FAIL] apcp_3hr fallback failed: {e}")

        print("[FAIL] apcp 取得に失敗")
        return None

    # --- 通常の open ---
    try:
        ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=fkeys)  # type: ignore[arg-type]
        if varname in ds.variables:
            print(f"[OK] {varname} shape={ds[varname].shape}")
            return ds[varname]

        # r はフォールバック
        if varname == "r" and rh_fallback_func:
            print("[WARN] r not found → RH fallback を試行")
            rh = rh_fallback_func(ds, level_hPa=level)
            if rh is not None:
                print(f"[OK] r fallback shape={rh.shape}")
                return rh

        print(f"[WARN] {varname} が ds.variables に存在しません")
        return None

    except Exception as e:
        print(f"[FAIL] open_grib2_var_auto: {e}")
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
    drive_folder: Optional[str] = None,  # None or フォルダID。未指定なら Drive は no-op
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
    返り値: (panel_imgs: list[str], zip_path: str, drive_url: str)
    """
    def log(msg: str):
        print(msg)
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    os.makedirs(output_dir, exist_ok=True)

    # --- データ抽出（必要変数だけ開く） ----------------------------------------
    print("\n[DEBUG] --- パネル用データ抽出開始 ---")
    panel_datasets = {
        "gh_300": open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, rh_fallback_func=rh_fallback_func),
        "u_300":  open_grib2_var_auto("u", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "v_300":  open_grib2_var_auto("v", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "gh_500": open_grib2_var_auto("gh", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "u_500":  open_grib2_var_auto("u", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "v_500":  open_grib2_var_auto("v", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "t_700":  open_grib2_var_auto("t", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "r_700":  open_grib2_var_auto("r", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, rh_fallback_func=r_fallback_func if (r_fallback_func:=rh_fallback_func) else None),  # noqa: E731
        "t_500":  open_grib2_var_auto("t", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "t_850":  open_grib2_var_auto("t", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "u_850":  open_grib2_var_auto("u", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "v_850":  open_grib2_var_auto("v", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "w_700":  open_grib2_var_auto("w", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "r_850":  open_grib2_var_auto("r", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, rh_fallback_func=rh_fallback_func),
        "u10":    open_grib2_var_auto("u10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "v10":    open_grib2_var_auto("v10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        "apcp":   open_grib2_var_auto("apcp", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, apcp_3hr_func=apcp_3hr_func),
        "prmsl":  open_grib2_var_auto("prmsl", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
    }

    print("\n[DEBUG] --- panel_datasets summary ---")
    for k, v in panel_datasets.items():
        if v is None:
            print(f"[WARN] {k}: None")
        else:
            print(f"[OK] {k}: shape={getattr(v, 'shape', None)} dims={getattr(v, 'dims', None)}")

    # --- パネル定義（必要に応じて get_panel_def_* を差し替え） -------------------
    print("\n[DEBUG] --- パネル定義呼び出し ---")
    panel_def = get_panel_def_japan(panel_datasets)  # 全国と同じ描画セットを流用
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
            n_steps = (ds.sizes["step"] if (ds is not None and hasattr(ds, "sizes") and "step" in ds.sizes) else 0)
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

    # --- Zip & Drive（任意） ----------------------------------------------------
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

    # 行数をパディング
    if len(panel_def) < nrows:
        panel_def = panel_def + [(None, None, "")] * (nrows - len(panel_def))

    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(ncols * 3, nrows * 3),
        constrained_layout=True,
        subplot_kw=dict(projection=ccrs.PlateCarree()),
    )

    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])  # type: ignore[index]
    elif nrows == 1:
        axes = axes[np.newaxis, :]  # type: ignore[index]
    elif ncols == 1:
        axes = axes[:, np.newaxis]  # type: ignore[index]

    # 描画
    for row, (plot_func, ds, title) in enumerate(panel_def):
        # step 数
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

    # 時刻ラベル
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
    """
    代表的な filter_by_keys を切り替えながら “開ける変数名” をログに出す。
    トラブルシュート用ユーティリティ。
    """
    combos = [
        {"typeOfLevel": "isobaricInhPa", "level": 850},
        {"typeOfLevel": "isobaricInhPa", "level": 700},
        {"typeOfLevel": "isobaricInhPa", "level": 500},
        {"typeOfLevel": "heightAboveGround", "level": 10, "stepType": "instant"},
        {"typeOfLevel": "meanSea", "stepType": "instant"},
        {"stepType": "accum"},
        {"stepType": "avg"},
        {"stepType": "instant"},
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
