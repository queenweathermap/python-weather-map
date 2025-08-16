# -*- coding: utf-8 -*-
# scripts/gpv_panel_daily_japan.py


from __future__ import annotations
import os, gc, argparse, datetime, warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import requests
from module.core.gpv_downloader import GPV_MIRROR_URLS
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.panel_utils import make_universal_weather_panel
from module.plotter.gpv_plotter_universal import open_grib2_var_auto

def _envint(k, d): 
    try: return int(os.environ.get(k, str(d)))
    except: return d

def _find_and_download(base_dir="./data", days_back=2,
                       cycle_hours=(0,21,18,15,12,9,6,3),
                       fh_band_gsm="FD0000-0100", fh_band_msm="FH00-15"):
    from module.core.gpv_downloader import list_files_on_server
    base = GPV_MIRROR_URLS[0]
    now = datetime.datetime.utcnow()
    for dd in range(days_back+1):
        day = now - datetime.timedelta(days=dd)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y,m,d,hh = dt.strftime("%Y %m %d %H").split()
            url = f"{base}/{y}/{m}/{d}/"
            gsm = list_files_on_server(dt,"GSM_GPV_Rjp_Gll0p1deg_L-pall",fh_band_gsm)
            m1  = list_files_on_server(dt,"MSM_GPV_Rjp_L-pall",fh_band_msm)
            m2  = list_files_on_server(dt,"MSM_GPV_Rjp_Lsurf",fh_band_msm)
            if gsm and m1 and m2:
                os.makedirs(base_dir, exist_ok=True)
                out=[]
                for fn in [gsm[0], m1[0], m2[0]]:
                    p = os.path.join(base_dir, fn)
                    if not os.path.exists(p):
                        r = requests.get(f"{url}{fn}", timeout=60); r.raise_for_status()
                        open(p,"wb").write(r.content)
                    out.append(p)
                return y+m+d, hh, out
    raise FileNotFoundError("GPVが見つかりません")

def _guess_steps(paths):
    cand = [("gh",300,"isobaric"), ("t",500,"isobaric"), ("u10",10,"heightAboveGround")]
    for var,lev,tol in cand:
        da = open_grib2_var_auto(var, lev, *paths, tol)
        if da is not None and hasattr(da,"sizes") and "step" in da.sizes:
            return int(da.sizes["step"])
    return 0

def main():
    import matplotlib
    matplotlib.use("Agg")

    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["top","bottom"], required=True,
                    help="top: 上3段, bottom: 下3段")
    ap.add_argument("--ncols", type=int, default=_envint("PANEL_NCOLS", 6))
    ap.add_argument("--dpi", type=int, default=_envint("PANEL_DPI", 120))
    ap.add_argument("--max_pages", type=int, default=_envint("PANEL_MAX_PAGES", 1))
    args = ap.parse_args()

    ncols = max(1, args.ncols); dpi = max(60, args.dpi); maxp = max(0, args.max_pages)

    ymd, hh, paths = _find_and_download()
    steps = _guess_steps(paths)
    if steps <= 0: raise RuntimeError("stepが取得できません")

    # 変数を開く（必要最低限は既存の panel_def に依存）
    ds = {
        "gh_300": open_grib2_var_auto("gh",300,*paths,"isobaric"),
        "u_300":  open_grib2_var_auto("u",300,*paths,"isobaric"),
        "v_300":  open_grib2_var_auto("v",300,*paths,"isobaric"),
        "gh_500": open_grib2_var_auto("gh",500,*paths,"isobaric"),
        "u_500":  open_grib2_var_auto("u",500,*paths,"isobaric"),
        "v_500":  open_grib2_var_auto("v",500,*paths,"isobaric"),
        "t_700":  open_grib2_var_auto("t",700,*paths,"isobaric"),
        "r_700":  open_grib2_var_auto("r",700,*paths,"isobaric"),
        "t_850":  open_grib2_var_auto("t",850,*paths,"isobaric"),
        "u_850":  open_grib2_var_auto("u",850,*paths,"isobaric"),
        "v_850":  open_grib2_var_auto("v",850,*paths,"isobaric"),
        "w_700":  open_grib2_var_auto("w",700,*paths,"isobaric"),
        "r_850":  open_grib2_var_auto("r",850,*paths,"isobaric"),
        "prmsl":  open_grib2_var_auto("prmsl",None,*paths,None),
        "u10":    open_grib2_var_auto("u10",10,*paths,"heightAboveGround"),
        "v10":    open_grib2_var_auto("v10",10,*paths,"heightAboveGround"),
    }
    full_def = get_panel_def_japan(ds)   # 6行の定義が返る前提
    if args.part == "top":
        panel_def = full_def[:3]
    else:
        panel_def = full_def[3:6]

    extent = REGION_EXTENTS["japan"]
    os.makedirs("output", exist_ok=True)

    pages = (steps + ncols - 1)//ncols
    if maxp > 0: pages = min(pages, maxp)

    for page in range(pages):
        tag = f"{ymd}_UTC{hh}_{args.part}_p{page+1}"
        make_universal_weather_panel(
            save_dir="output",
            panel_def=panel_def,
            times=None,
            init_time_str=f"{ymd}_UTC{hh}",
            city_name="japan",
            ncols=ncols,
            nrows=len(panel_def),  # 3
            extent=extent,
            dpi=dpi,
            step=None,
            start_step=page*ncols,
            title_prefix=f"全国パネル（{args.part}）",
            filename_tag=tag,
        )
    print("[OK] done:", args.part)

if __name__ == "__main__":
    main()
