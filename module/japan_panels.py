# -*- coding: utf-8 -*-
# module/japan_panels.py

from __future__ import annotations
import os, datetime, warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import requests
from module.core.gpv_downloader import GPV_MIRROR_URLS
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.panel_utils import make_universal_weather_panel
from module.plotter.gpv_plotter_universal import open_grib2_var_auto


def _find_and_download(base_dir="./data", days_back=2,
                       cycle_hours=(0, 21, 18, 15, 12, 9, 6, 3),
                       fh_band_gsm="FD0000-0100", fh_band_msm="FH00-15"):
    """入手可能な最新の GSM+MSM(2種) を探してダウンロード。"""
    from module.core.gpv_downloader import list_files_on_server
    base = GPV_MIRROR_URLS[0]
    now = datetime.datetime.utcnow()
    for dd in range(days_back + 1):
        day = now - datetime.timedelta(days=dd)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = dt.strftime("%Y %m %d %H").split()
            url = f"{base}/{y}/{m}/{d}/"
            gsm = list_files_on_server(dt, "GSM_GPV_Rjp_Gll0p1deg_L-pall", fh_band_gsm)
            m1  = list_files_on_server(dt, "MSM_GPV_Rjp_L-pall", fh_band_msm)
            m2  = list_files_on_server(dt, "MSM_GPV_Rjp_Lsurf", fh_band_msm)
            if gsm and m1 and m2:
                os.makedirs(base_dir, exist_ok=True)
                out = []
                for fn in [gsm[0], m1[0], m2[0]]:
                    p = os.path.join(base_dir, fn)
                    if not os.path.exists(p):
                        r = requests.get(f"{url}{fn}", timeout=60); r.raise_for_status()
                        open(p, "wb").write(r.content)
                    out.append(p)
                return y + m + d, hh, out
    raise FileNotFoundError("GPVが見つかりません")


def _guess_steps(paths):
    """step 次元の長さ（予報本数）をざっくり推定。"""
    cand = [("gh", 300, "isobaric"), ("t", 500, "isobaric"), ("u10", 10, "heightAboveGround")]
    for var, lev, tol in cand:
        da = open_grib2_var_auto(var, lev, *paths, tol)
        if da is not None and hasattr(da, "sizes") and "step" in da.sizes:
            return int(da.sizes["step"])
    return 0


def render_japan_panels(
    part: str | None,
    ncols: int,
    dpi: int,
    max_pages: int,
    output_dir: str = "output",
) -> list[str]:
    """
    全国パネルを描画して JPG を保存。
    part: None=全段, "top"=上半分(3段), "bottom"=下半分(3段)
    返り値: 保存ファイルのパス一覧
    """
    # 描画バックエンド
    import matplotlib
    matplotlib.use("Agg")

    ncols = max(1, int(ncols))
    dpi = max(60, int(dpi))
    max_pages = max(0, int(max_pages))

    # 1) データを取得
    ymd, hh, paths = _find_and_download()
    steps = _guess_steps(paths)
    if steps <= 0:
        raise RuntimeError("stepが取得できません")

    # 2) 必要な変数を開く
    ds = {
        "gh_300": open_grib2_var_auto("gh", 300, *paths, "isobaric"),
        "u_300":  open_grib2_var_auto("u", 300, *paths, "isobaric"),
        "v_300":  open_grib2_var_auto("v", 300, *paths, "isobaric"),
        "gh_500": open_grib2_var_auto("gh", 500, *paths, "isobaric"),
        "u_500":  open_grib2_var_auto("u", 500, *paths, "isobaric"),
        "v_500":  open_grib2_var_auto("v", 500, *paths, "isobaric"),
        "t_700":  open_grib2_var_auto("t", 700, *paths, "isobaric"),
        "r_700":  open_grib2_var_auto("r", 700, *paths, "isobaric"),
        "t_850":  open_grib2_var_auto("t", 850, *paths, "isobaric"),
        "u_850":  open_grib2_var_auto("u", 850, *paths, "isobaric"),
        "v_850":  open_grib2_var_auto("v", 850, *paths, "isobaric"),
        "w_700":  open_grib2_var_auto("w", 700, *paths, "isobaric"),
        "r_850":  open_grib2_var_auto("r", 850, *paths, "isobaric"),
        "prmsl":  open_grib2_var_auto("prmsl", None, *paths, None),
        "u10":    open_grib2_var_auto("u10", 10, *paths, "heightAboveGround"),
        "v10":    open_grib2_var_auto("v10", 10, *paths, "heightAboveGround"),
    }

    # 3) パネル定義（6行想定）→ 上下に分割
    full_def = get_panel_def_japan(ds)
    if part == "top":
        panel_def = full_def[:3]
        title_suffix = "（top）"
    elif part == "bottom":
        panel_def = full_def[3:6]
        title_suffix = "（bottom）"
    else:
        panel_def = full_def
        title_suffix = ""

    extent = REGION_EXTENTS["japan"]
    os.makedirs(output_dir, exist_ok=True)

    pages = (steps + ncols - 1) // ncols
    if max_pages > 0:
        pages = min(pages, max_pages)

    saved = []
    for page in range(pages):
        tag = f"{ymd}_UTC{hh}_{(part or 'all')}_p{page+1}"
        out = make_universal_weather_panel(
            save_dir=output_dir,
            panel_def=panel_def,
            times=None,
            init_time_str=f"{ymd}_UTC{hh}",
            city_name="japan",
            ncols=ncols,
            nrows=len(panel_def),
            extent=extent,
            dpi=dpi,
            step=None,
            start_step=page * ncols,
            title_prefix=f"全国パネル{title_suffix}",
            filename_tag=tag,
        )
        # make_universal_weather_panel が戻り値を返さない場合に備えて推測
        if isinstance(out, str):
            saved.append(out)
    # 既知の関数がパスを返さない実装なら、output_dir をスキャン
    if not saved:
        for fn in sorted(os.listdir(output_dir)):
            if fn.lower().endswith(".jpg"):
                saved.append(os.path.join(output_dir, fn))
    return saved
