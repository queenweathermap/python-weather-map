# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_japan.py
# -----------------------------------------------------------------------------
# 全国（GSM+MSMハイブリッド）パネル自動生成
#  - 列＝連続 step（+0h, +3h, +6h ...）を横に並べた「1枚画像」をページごとに生成
#  - 生成されたページ画像は後段ジョブ（aggregate_and_send.py）で1通にまとめて送信
#  - Google Drive 等の保存は行わない“保存しない運用”
#
# 描画調整（ENV もしくは CLI 引数で指定、CLI優先）:
#   PANEL_NCOLS     / --ncols      : 列数（既定 4）
#   PANEL_DPI       / --dpi        : DPI（既定 120）
#   PANEL_MAX_PAGES / --max_pages  : 出力ページ上限（既定 1。0=全ページ）
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


# -------------------------------- main ---------------------------------------
def _envint(name: str, default: int) -> int:
    """環境変数の整数取得（未設定や不正値は default）"""
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def main():
    # ヘッドレス描画
    import matplotlib
    matplotlib.use("Agg")

    # ---- 引数/ENV（CLI優先）----
    parser = argparse.ArgumentParser()
    parser.add_argument("--ncols", type=int, default=_envint("PANEL_NCOLS", 4))
    parser.add_argument("--dpi", type=int, default=_envint("PANEL_DPI", 120))
    parser.add_argument(
        "--max_pages",
        type=int,
        default=_envint("PANEL_MAX_PAGES", 1),
        help="生成ページ数の上限。まずは 1 で“横長1枚/ページ”を安定化。0=全ページ",
    )
    args = parser.parse_args()

    NCOLS = max(1, args.ncols)
    DPI   = max(60, args.dpi)
    MAXP  = max(0, args.max_pages)

    base_dir = "./data"
    output_dir = "./output"
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")

    # ✅ ここで初期化しておく
    saved_imgs: list[str] = []

    try:
        # 1) 必要なGRIB2（3本）を取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir
        )

        # 2) 利用可能step数（3h刻み）
        arr = open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric")
        total_steps = int(arr.sizes.get("step", 0)) or 0
        del arr
        gc.collect()
        if total_steps <= 0:
            raise RuntimeError("step 次元が取得できませんでした")

        # 3) 各変数をopen（isobaric/surface混在OK）
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

        # 4) ページ分割で 1ページ=NCOLS列 の横長画像を順次出力
        os.makedirs(output_dir, exist_ok=True)
        pages = (total_steps + NCOLS - 1) // NCOLS
        if MAXP > 0:
            pages = min(pages, MAXP)

        saved_imgs = []
        for page in range(pages):
            start_step = page * NCOLS
            tag = f"{ymd}_UTC{hh}_p{page+1}"
            imgs = make_universal_weather_panel(
                save_dir=output_dir,
                panel_def=panel_def,
                times=None,
                init_time_str=f"{ymd}_UTC{hh}",
                city_name="japan",
                ncols=NCOLS,                  # 列＝連続 step
                nrows=len(panel_def),         # 行＝panel_def（変数群）
                extent=extent,
                dpi=DPI,
                step=None,                    # None→列は start_step+col
                start_step=start_step,
                title_prefix="全国パネル",
                filename_tag=tag,
            )
            saved_imgs.extend(imgs)

        print(f"[OK] 出力完了: {len(saved_imgs)} 枚 -> {output_dir}")

        # 5) Slackに軽く実行完了のみ通知（送信は集約ジョブ）
        if slack_channel:
            send_slack_text(
                channel=slack_channel,
                message=(
                    f":white_check_mark: 生成完了 {ymd} UTC{hh}\n"
                    f"列={NCOLS}, DPI={DPI}, ページ={len(saved_imgs)}"
                ),
            )

    except Exception as e:
        if slack_channel:
            send_slack_text(channel=slack_channel, message=f":x: 生成失敗: {e}")
        raise


if __name__ == "__main__":
    main()
