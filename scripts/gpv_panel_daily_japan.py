# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_japan.py
# -----------------------------------------------------------------------------
# 全国（GSM+MSMハイブリッド）パネル自動生成 → ZIP化 → メール添付送信
# ※ Google Drive 永続保存は一切行わない（保存しない運用）
#
# 必要な環境変数（GitHub Actions Secrets を推奨）:
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
#   MAIL_FROM, MAIL_TO, (任意) MAIL_SUBJECT_PREFIX
#   SLACK_CHANNEL_ID (任意、未設定ならSlack通知をスキップ)
#
# 依存モジュール（本リポジトリ内）:
#   - module.plotter.gpv_plotter_universal: open_grib2_var_auto, make_universal_weather_panel
#   - module.panel_definitions: get_panel_def_japan, REGION_EXTENTS
#   - module.core.gpv_downloader: GPV_MIRROR_URLS, list_files_on_server
#   - module.utils.mail_utils: send_mail
#   - module.utils.zip_utils: to_zip_bytes_from_dir
#   - module.utils.slack_utils: send_slack_text（任意）
#
# 実行例:
#   python scripts/gpv_panel_daily_japan.py --forecast_hour 0
# =============================================================================

import os
import sys
import gc
import zipfile
import argparse
import datetime
import warnings
import shutil

warnings.filterwarnings("ignore", category=FutureWarning)

from module.plotter.gpv_plotter_universal import (
    open_grib2_var_auto,
    make_universal_weather_panel,
)
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text  # 環境変数未設定なら使われない想定
from module.core.gpv_downloader import GPV_MIRROR_URLS

import requests


def find_and_download_gpv_files(
    base_dir: str = "./data",
    days_back: int = 2,
    cycle_hours=(0, 21, 18, 15, 12, 9, 6, 3),
    fh_band_gsm: str = "FD0000-0100",
    fh_band_msm: str = "FH00-15",
):
    """
    RISH の日付パスを上から走査し、GSM/MSMの必要 bin が3本とも見つかった時点でDLして返す。
    404が混じる前提で、indexベースの列挙関数を使って存在確認を行う。
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
                target_files = [gsm_files[0], msm_l_pall[0], msm_lsurf[0]]
                paths = []
                os.makedirs(base_dir, exist_ok=True)
                for fname in target_files:
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


def main():
    # Aggバックエンド（ヘッドレス）
    import matplotlib

    matplotlib.use("Agg")

    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast_hour", type=int, default=0, help="3h刻み（0,3,6, ...）")
    args = parser.parse_args()
    forecast_hour = int(args.forecast_hour)
    print(f"[INFO] forecast_hour={forecast_hour}")

    base_dir = "./data"
    output_dir = "./output"
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")

    try:
        # 1) 必要な GRIB2 を取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir
        )

        # 2) step 計算（3h 刻み）
        arr = open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric")
        nsteps = arr.sizes.get("step", 9)
        del arr
        gc.collect()

        step = forecast_hour // 3
        if step < 0 or step >= nsteps:
            raise ValueError(f"指定 forecast_hour={forecast_hour} が有効範囲外（nsteps={nsteps}）")

        # 3) 必要変数を開く（isobaric/surface混在に対応するユニバーサルオープナ）
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

        os.makedirs(output_dir, exist_ok=True)
        _ = make_universal_weather_panel(
            save_dir=output_dir,
            panel_def=panel_def,
            times=None,
            init_time_str=f"{ymd}_UTC{hh}",
            city_name="japan",
            ncols=1,
            nrows=len(panel_def),
            extent=extent,
            dpi=80,
            step=step,
        )

        # 4) 出力ディレクトリを ZIP（メモリ上）→ メール添付で送信
        zip_bytes = to_zip_bytes_from_dir(output_dir)
        subject = f"全国パネル {ymd} UTC{hh} +{forecast_hour}h"
        body = "全国（GSM+MSM）パネル出力一式をZIP添付します（保存なし運用）。"

        msg_id = send_mail(
            to_addrs=os.environ.get("MAIL_TO", ""),
            subject=subject,
            body=body,
            attachment_blobs=[(f"japan_panel_{ymd}_UTC{hh}_fh{forecast_hour:02}.zip", zip_bytes, "application/zip")],
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id}")

        # 任意: Slack テキスト通知
        if slack_channel:
            try:
                fnames = ", ".join(sorted(os.listdir(output_dir)))
                send_slack_text(
                    channel=slack_channel,
                    message=f":large_blue_circle: 全国パネル送信 {ymd} UTC{hh} +{forecast_hour}h\nMessage-ID: {msg_id}\nfiles: {fnames}",
                )
            except Exception as _:
                pass

    except Exception as e:
        if os.environ.get("SLACK_CHANNEL_ID"):
            send_slack_text(channel=os.environ["SLACK_CHANNEL_ID"], message=f":x: 全国パネル失敗: {e}")
        print(f"[ERROR] {e}")
        raise
    finally:
        # 5) 後片付け（実行環境からも削除）※終了後にランナーは破棄されるが念のため
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
