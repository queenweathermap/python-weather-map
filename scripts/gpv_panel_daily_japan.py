# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_japan.py
# -----------------------------------------------------------------------------
# 全国（GSM+MSMハイブリッド）パネル自動生成（2枚構成）
#  - 「上3段」「下3段」をそれぞれ横に ncols 列（+0h, +3h, ...）で並べた1枚ずつを出力
#  - 生成された2枚は後段ジョブ（aggregate_and_send.py）で1通にまとめて送信
#  - Google Drive 等の保存は行わない“保存しない運用”
#
# 描画調整（ENV もしくは CLI 引数で指定、CLI優先）:
#   PANEL_NCOLS / --ncols : 横列数（既定 16 推奨。利用可能 step 数以下に自動クリップ）
#   PANEL_DPI   / --dpi   : DPI（既定 120）
# =============================================================================

from __future__ import annotations

import os
import gc
import argparse
import datetime
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

import requests

from module.core.gpv_downloader import GPV_MIRROR_URLS
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.utils.slack_utils import send_slack_text  # 任意（未設定なら無視）
from module.panel_utils import make_universal_weather_panel  # 複数列1枚の描画コア
from module.plotter.gpv_plotter_universal import open_grib2_var_auto


# ------------------------------ GPV DL ---------------------------------------
def find_and_download_gpv_files(
    base_dir: str = "./data",
    days_back: int = 2,
    cycle_hours=(0, 21, 18, 15, 12, 9, 6, 3),
    fh_band_gsm: str = "FD0000-0100",
    fh_band_msm: str = "FH00-15",
):
    """
    RISH公開ディレクトリを新しい方から走査し、GSM/MSMの必要bin
    （GSM L-pall、MSM L-pall、MSM Lsurf）がそろった初回でDLして返す。
    """
    from module.core.gpv_downloader import list_files_on_server

    base_url = GPV_MIRROR_URLS[0]
    now = datetime.datetime.utcnow()

    for day_delta in range(days_back + 1):
        day = now - datetime.timedelta(days=day_delta)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = dt.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"

            gsm_files = list_files_on_server(dt, "GSM_GPV_Rjp_Gll0p1deg_L-pall", fh_band_gsm)
            msm_l_pall = list_files_on_server(dt, "MSM_GPV_Rjp_L-pall", fh_band_msm)
            msm_lsurf  = list_files_on_server(dt, "MSM_GPV_Rjp_Lsurf", fh_band_msm)

            if gsm_files and msm_l_pall and msm_lsurf:
                targets = [gsm_files[0], msm_l_pall[0], msm_lsurf[0]]
                os.makedirs(base_dir, exist_ok=True)
                paths = []
                for fname in targets:
                    url = f"{data_url}{fname}"
                    local = os.path.join(base_dir, fname)
                    if not os.path.exists(local):
                        r = requests.get(url, timeout=60)
                        r.raise_for_status()
                        with open(local, "wb") as f:
                            f.write(r.content)
                        print(f"[OK] DL: {local}")
                    paths.append(local)
                return y + m + d, hh, paths

    raise FileNotFoundError("利用可能なGSM/MSM GPVファイルが見つかりません。")


# ------------------------------ helpers --------------------------------------
def _envint(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except Exception:
        return default

def _guess_total_steps(gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) -> int:
    """利用可能な step 数を複数の候補から推定。失敗時 0。"""
    candidates = [
        ("gh", 300, "isobaric"),
        ("t", 500, "isobaric"),
        ("t", 700, "isobaric"),
        ("r", 700, "isobaric"),
        ("prmsl", None, None),
        ("u10", 10, "heightAboveGround"),
    ]
    for var, lev, tol in candidates:
        da = open_grib2_var_auto(var, lev, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, tol)
        if da is not None and hasattr(da, "sizes") and "step" in da.sizes:
            try:
                n = int(da.sizes["step"])
                if n > 0:
                    print(f"[INFO] step count from {var}/{lev}: {n}")
                    return n
            except Exception:
                pass
    print("[WARN] step 数を推定できませんでした")
    return 0


# -------------------------------- main ---------------------------------------
def main():
    import matplotlib
    matplotlib.use("Agg")

    # 引数
    parser = argparse.ArgumentParser()
    parser.add_argument("--ncols", type=int, default=_envint("PANEL_NCOLS", 16))
    parser.add_argument("--dpi", type=int, default=_envint("PANEL_DPI", 120))
    args = parser.parse_args()

    NCOLS = max(1, args.ncols)
    DPI   = max(60, args.dpi)

    base_dir = "./data"
    output_dir = "./output"
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")

    try:
        # 1) 必要なGRIB2（3本）を取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir
        )

        # 2) 利用可能 step 数を把握（3h刻み）
        total_steps = _guess_total_steps(gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path)
        if total_steps <= 0:
            raise RuntimeError("step 次元が取得できませんでした（open_grib2_var_auto が全て None）")

        # 3) 描画に使う変数群をopen（isobaric/surface混在OK）
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
            "prmsl":  open_grib2_var_auto("prmsl", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
            "u10":    open_grib2_var_auto("u10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
            "v10":    open_grib2_var_auto("v10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
        }

        panel_def = get_panel_def_japan(panel_datasets)
        extent = REGION_EXTENTS["japan"]

        # 4) 「上3段」「下3段」をそれぞれ横長で出力（合計2枚）
        os.makedirs(output_dir, exist_ok=True)
        # 利用可能 step 数に合わせて列数をクリップ
        ncols = max(1, min(NCOLS, total_steps))
        start_step = 0  # 必要なら現在時刻からのオフセットに変更可

        groups = [
            ("top",    panel_def[:3]),
            ("bottom", panel_def[3:6]),
        ]

        saved_imgs = []
        for label, rows in groups:
            tag = f"{ymd}_UTC{hh}_{label}"
            imgs = make_universal_weather_panel(
                save_dir=output_dir,
                panel_def=rows,              # ★ 3行だけ
                times=None,
                init_time_str=f"{ymd}_UTC{hh}",
                city_name="japan",
                ncols=ncols,                 # ★ 横 ncols 列
                nrows=len(rows),             # 3
                extent=extent,
                dpi=DPI,
                step=None,                   # 列は start_step + col
                start_step=start_step,
                title_prefix="全国パネル",
                filename_tag=tag,            # panel_japan_YYYYMMDD_UTCHH_top.jpg / bottom.jpg
            )
            saved_imgs.extend(imgs)

        print(f"[OK] 出力完了（2枚）: {saved_imgs}")

        # 5) Slackに軽く完了通知（画像は後段でメール送信）
        if slack_channel:
            try:
                send_slack_text(
                    channel=slack_channel,
                    message=(
                        f":white_check_mark: 生成完了 {ymd} UTC{hh}\n"
                        f"列={ncols}, DPI={DPI}, 出力={len(saved_imgs)}枚（top/bottom）"
                    ),
                )
            except Exception:
                pass

    except Exception as e:
        if os.environ.get("SLACK_CHANNEL_ID"):
            try:
                send_slack_text(channel=os.environ["SLACK_CHANNEL_ID"], message=f":x: 生成失敗: {e}")
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
