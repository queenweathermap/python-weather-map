# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_japan.py
# -----------------------------------------------------------------------------
# 全国（GSM+MSMハイブリッド）パネル自動生成（複数列を1枚に）→ メール1通で送信
#  - Google Drive 永続保存は行わない（“保存しない”運用）
#  - 列＝連続step（+0h, +3h, +6h ...）を横に並べた 1 枚を生成
#  - 全stepをカバーするためのページ分割にも対応（列数×ページで網羅）
#
# 主要ENV（GitHub Actions Secrets 推奨／mail_utilsの統一名に準拠）
#   FROM_EMAIL, TO_EMAIL, SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
#   MAIL_SUBJECT_PREFIX   : 件名先頭（例 "[Japan]"）
#   MAIL_ATTACH_AS_ZIP    : "1" なら原画像群をZIPでも同梱（mail_utils側で処理）
#   MAX_MAIL_SIZE_MB      : 合計サイズ上限（既定20MB、超過で自動ZIP）
#   SLACK_BOT_TOKEN / SLACK_CHANNEL_ID : あれば同報（mail_utils側で1回だけ）
#
# パネル出力の調整ENV / CLI
#   PANEL_NCOLS           : 列数（既定 4） 例: 4列なら +0,+3,+6,+9h を1枚
#   PANEL_DPI             : 画像DPI（既定 120）
#   PANEL_MAX_PAGES       : 生成ページ数の上限（既定 0=全ページ）
#   --ncols, --dpi, --max_pages でも指定可（ENVよりCLI優先）
#
# 実行例:
#   python scripts/gpv_panel_daily_japan.py --ncols 4 --max_pages 0
# =============================================================================

from __future__ import annotations

import os
import sys
import gc
import argparse
import datetime
import warnings
import shutil

warnings.filterwarnings("ignore", category=FutureWarning)

import requests

from module.core.gpv_downloader import GPV_MIRROR_URLS
from module.panel_definitions import get_panel_def_japan, REGION_EXTENTS
from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text  # 任意（環境変数未設定なら何もしない）

# ここが“複数列1枚”対応のパネル描画コア
from module.panel_utils import make_universal_weather_panel
from module.plotter.gpv_plotter_universal import open_grib2_var_auto


# -----------------------------------------------------------------------------
# GPVの存在チェック＆ダウンロード
# -----------------------------------------------------------------------------
def find_and_download_gpv_files(
    base_dir: str = "./data",
    days_back: int = 2,
    cycle_hours=(0, 21, 18, 15, 12, 9, 6, 3),
    fh_band_gsm: str = "FD0000-0100",
    fh_band_msm: str = "FH00-15",
):
    """
    RISHの公開ディレクトリを新しい方から走査し、GSM/MSMの必要binが
    3本（GSM L-pall、MSM L-pall、MSM Lsurf）そろった初回でDLして返す。
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


# -----------------------------------------------------------------------------
# メイン
# -----------------------------------------------------------------------------
def main():
    # ヘッドレス描画
    import matplotlib
    matplotlib.use("Agg")

    # ---- 引数/ENV ----
    parser = argparse.ArgumentParser()
    parser.add_argument("--ncols", type=int, default=int(os.environ.get("PANEL_NCOLS", "4")))
    parser.add_argument("--dpi", type=int, default=int(os.environ.get("PANEL_DPI", "120")))
    parser.add_argument("--max_pages", type=int, default=int(os.environ.get("PANEL_MAX_PAGES", "0")),
                        help="生成ページ数の上限。0なら全stepを網羅")
    args = parser.parse_args()

    NCOLS = max(1, int(args.ncols))
    DPI   = max(60, int(args.dpi))
    MAXP  = max(0, int(args.max_pages))  # 0 = all

    base_dir = "./data"
    output_dir = "./output"
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")

    try:
        # 1) GPVファイル3本を入手
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir
        )

        # 2) 利用可能な step 数を把握（3時間刻み）
        arr = open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric")
        total_steps = int(arr.sizes.get("step", 0)) or 0
        del arr
        gc.collect()
        if total_steps <= 0:
            raise RuntimeError("step 次元が取得できませんでした")

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

        # 4) 複数列パネルを“ページ分割”で生成
        os.makedirs(output_dir, exist_ok=True)
        pages = (total_steps + NCOLS - 1) // NCOLS
        if MAXP > 0:
            pages = min(pages, MAXP)

        saved_imgs = []
        for page in range(pages):
            start_step = page * NCOLS
            filename_tag = f"{ymd}_UTC{hh}_p{page+1}"
            imgs = make_universal_weather_panel(
                save_dir=output_dir,
                panel_def=panel_def,
                times=None,
                init_time_str=f"{ymd}_UTC{hh}",
                city_name="japan",
                ncols=NCOLS,                   # ★ 列＝連続step
                nrows=len(panel_def),
                extent=extent,
                dpi=DPI,
                step=None,                     # ★ None → 列ごとに start_step + col を自動表示
                start_step=start_step,         # ★ ページング（0, ncols, 2*ncols, ...）
                title_prefix="全国パネル",
                filename_tag=filename_tag,
            )
            saved_imgs.extend(imgs)

        # 5) メール 1 通で送信（mail_utils が複数添付でも“1通”にまとめる）
        subject = f"全国パネル {ymd} UTC{hh}（{NCOLS}列×{len(saved_imgs)}ページ）"
        body = (
            f"{ymd} UTC{hh} 初期の全国パネルを {NCOLS}列で出力しました。\n"
            f"ページ数: {len(saved_imgs)}\n"
            f"列あたり +3h 進行（例: 列1=+0h, 列2=+3h ...）\n"
        )
        msg_id = send_mail(
            subject=subject,
            body=body,
            attachment_paths=saved_imgs,   # ← 複数添付でも 1 通で送信
            is_html=False,
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id}")

        # 6) 任意：Slackテキスト通知（mail_utilsでも成功/失敗は1回通知される）
        if slack_channel:
            try:
                fnames = ", ".join(os.path.basename(p) for p in saved_imgs[:6])
                more = f"...(+{len(saved_imgs)-6} files)" if len(saved_imgs) > 6 else ""
                send_slack_text(
                    channel=slack_channel,
                    message=(
                        f":large_blue_circle: 全国パネル送信 {ymd} UTC{hh}\n"
                        f"{NCOLS}列 × {len(saved_imgs)}ページ\n"
                        f"Message-ID: {msg_id}\n"
                        f"files: {fnames} {more}"
                    ),
                )
            except Exception:
                pass

    except Exception as e:
        # エラー時も可能ならSlackに通知
        if os.environ.get("SLACK_CHANNEL_ID"):
            try:
                send_slack_text(channel=os.environ["SLACK_CHANNEL_ID"], message=f":x: 全国パネル失敗: {e}")
            except Exception:
                pass
        print(f"[ERROR] {e}")
        raise
    finally:
        # 7) 後片付け（ランナーは破棄されるが念のため）
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
