# ===============================================================
# scripts/gpv_panel_daily_japan.py
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-30 ファイル自動判定・変数/層ごと動的抽出対応
# ===============================================================

import os
import sys
import datetime
import requests
import xarray as xr

from module.panel_definitions import REGION_EXTENTS, get_panel_def_japan
from module.utils.slack_utils import send_slack_text
from module.utils.drive_utils import upload_to_drive
from module.core.gpv_downloader import list_files_on_server, GPV_MIRROR_URLS
from module.plotter.gpv_plotter_universal import dump_grib_vars


# ---- 変数・層ごと自動で最適なファイルを選ぶ関数
def select_file_for_var(var, level, gsm_path, msm_pall_path, msm_lsurf_path):
    """
    変数名とレベルに応じて最適なファイルパスを返す
    """
    # 高層（300,500,700）のgh/u/v/t/r: GSM優先
    if var in ["gh", "u", "v", "t", "r"] and level in [300, 500, 700]:
        return gsm_path
    # 850/w_700/r_850はMSM
    if var in ["t", "u", "v", "r"] and level == 850:
        return msm_pall_path
    if var == "w" and level == 700:
        return msm_pall_path
    # 地上（10m）やprmsl, apcpはMSM_Lsurf
    if var in ["u10", "v10", "apcp", "prmsl"]:
        return msm_lsurf_path
    # 万が一のため
    return msm_pall_path

def open_grib2_var_auto(varname, level=None, gsm_path=None, msm_pall_path=None, msm_lsurf_path=None, type_of_level=None, stepType=None):
    """
    変数・層から自動的にファイルを選びopen_grib2_varを呼ぶ
    """
    file_path = select_file_for_var(varname, level, gsm_path, msm_pall_path, msm_lsurf_path)
    filter_keys = {}
    # --- 必要なフィルタ指定を強化 ---
    if type_of_level:
        filter_keys['typeOfLevel'] = type_of_level
    if level is not None:
        if type_of_level == 'isobaric':
            filter_keys['isobaricInhPa'] = level
        elif type_of_level == 'heightAboveGround':
            filter_keys['level'] = level
    if stepType:
        filter_keys['stepType'] = stepType

    # --- 特殊: apcpだけはstepType=accum優先でトライ ---
    if varname == "apcp":
        for try_step in ["accum", "avg", "instant"]:
            filter_keys_mod = filter_keys.copy()
            filter_keys_mod['stepType'] = try_step
            try:
                ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys_mod)
                if varname in ds:
                    print(f"[OK] {varname} found with {filter_keys_mod}")
                    return ds[varname]
            except Exception as e:
                continue
        print(f"[WARN] open_grib2_var_auto failed for {varname} (file={file_path}): 全stepTypeトライ失敗")
        return None

    # --- 通常: 他変数 ---
    try:
        ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=filter_keys)
        return ds[varname] if varname in ds else None
    except Exception as e:
        msg = str(e)
        # multiple values for unique key
        if "multiple values for unique key" in msg:
            import re, ast
            candidates = re.findall(r"filter_by_keys=({.*?})", msg)
            for cand in candidates:
                try:
                    cand_dict = ast.literal_eval(cand)
                    ds = xr.open_dataset(file_path, engine="cfgrib", filter_by_keys=cand_dict)
                    if varname in ds:
                        print(f"[OK] {varname} found with {cand_dict}")
                        return ds[varname]
                except Exception:
                    continue
        print(f"[WARN] open_grib2_var_auto failed for {varname} (file={file_path}): {e}")
        return None


# --- GPVファイルの自動探索＆ダウンロード（あなたの最新実装そのまま）
def find_and_download_gpv_files(
    base_dir="./data",
    days_back=2,
    cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
    fh_band_gsm="FD0000-0100",
    fh_band_msm="FH00-15"
):
    base_url = GPV_MIRROR_URLS[0]
    now = datetime.datetime.utcnow()
    for day_delta in range(days_back):
        day = now - datetime.timedelta(days=day_delta)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = dt.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            gsm_files = list_files_on_server(dt, "GSM_GPV_Rjp_Gll0p1deg_L-pall", fh_band_gsm)
            msm_l_pall_files = list_files_on_server(dt, "MSM_GPV_Rjp_L-pall", fh_band_msm)
            msm_lsurf_files  = list_files_on_server(dt, "MSM_GPV_Rjp_Lsurf", fh_band_msm)
            if gsm_files and msm_l_pall_files and msm_lsurf_files:
                gsm_l_pall_fname = gsm_files[0]
                msm_l_pall_fname = msm_l_pall_files[0]
                msm_lsurf_fname  = msm_lsurf_files[0]
                file_paths = []
                for fname in [gsm_l_pall_fname, msm_l_pall_fname, msm_lsurf_fname]:
                    url = f"{data_url}{fname}"
                    local = os.path.join(base_dir, fname)
                    if not os.path.exists(local):
                        resp = requests.get(url)
                        if resp.status_code == 200:
                            os.makedirs(os.path.dirname(local), exist_ok=True)
                            with open(local, "wb") as f:
                                f.write(resp.content)
                            print(f"[OK] DL: {local}")
                        else:
                            print(f"[NG] DL: {url} (status={resp.status_code})")
                            break
                    file_paths.append(local)
                if len(file_paths) == 3:
                    return y+m+d, hh, file_paths
    raise FileNotFoundError("利用可能なGSM/MSM GPVファイルがindex.html上に見つかりません")

# --- メインバッチ処理 ---
def main():
    base_dir = "./data"
    output_dir = "./output"
    drive_folder = os.environ.get("DRIVE_FOLDER_ID")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")
    days_back = 2

    try:
        # 1. 必要ファイルDL＆パス取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir, days_back=days_back
        )

        # 本当にghの300hPaが入っているか確認
        ds = xr.open_dataset(gsm_l_pall_path, engine="cfgrib", filter_by_keys={"shortName": "gh"})
        print(ds['gh'].coords)
        print(ds['gh'].shape)
        # ここでダンプ
        print("==== GSM L-pall dump ====")
        dump_grib_vars(gsm_l_pall_path)
        print("==== MSM L-pall dump ====")
        dump_grib_vars(msm_l_pall_path)
        print("==== MSM Lsurf dump ====")
        dump_grib_vars(msm_lsurf_path)

        # 2. パネル用データ辞書を自動openで作成
        panel_datasets = {
            # GSM（高層）
            "gh_300": open_grib2_var_auto("gh", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "u_300":  open_grib2_var_auto("u", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "v_300":  open_grib2_var_auto("v", 300, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "gh_500": open_grib2_var_auto("gh", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "u_500":  open_grib2_var_auto("u", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "v_500":  open_grib2_var_auto("v", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "t_700":  open_grib2_var_auto("t", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "r_700":  open_grib2_var_auto("r", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "t_500":  open_grib2_var_auto("t", 500, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            # MSM（下層）
            "t_850":  open_grib2_var_auto("t", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "u_850":  open_grib2_var_auto("u", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "v_850":  open_grib2_var_auto("v", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "w_700":  open_grib2_var_auto("w", 700, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            "r_850":  open_grib2_var_auto("r", 850, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "isobaric"),
            # 地上
            "prmsl": open_grib2_var_auto("prmsl", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
            "u10":   open_grib2_var_auto("u10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
            "v10":   open_grib2_var_auto("v10", 10, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path, "heightAboveGround"),
            "apcp":  open_grib2_var_auto("apcp", None, gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path),
        }

        # 3. パネル定義取得→描画
        panel_def = get_panel_def_japan(panel_datasets)
        times = []
        init_time_str = f"{ymd}_{hh}UTC"

        from module.panel_utils import make_universal_weather_panel
        panel_imgs = make_universal_weather_panel(
            save_dir=output_dir,
            panel_def=panel_def,
            times=times,
            init_time_str=init_time_str,      # ヘッダ・右上
            city_name="japan",
            ncols=8,
            nrows=6,
            extent=REGION_EXTENTS["japan"],
            dpi=300
        )

        # 4. Driveアップロード→Slack通知
        drive_url = upload_to_drive(drive_folder, panel_imgs[0])
        msg = (
            f":large_blue_circle: 全国天気図パネル {ymd} UTC{hh}\n"
            f"{os.linesep.join(os.path.basename(f) for f in panel_imgs)}\n"
            f"{drive_url if drive_url else '(Driveアップロード失敗)'}"
        )
        send_slack_text(channel=slack_channel, message=msg)
        print("[OK] 全国パネル自動化 完了")

    except FileNotFoundError:
        send_slack_text(channel=slack_channel, message=":warning: 必要なGPVファイルが見つかりません（GSM/MSM/Lsurf）")
        sys.exit(1)
        pass

    except Exception as e:
        send_slack_text(channel=slack_channel, message=f":x: パネル生成失敗: {e}")
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
        pass
        
if __name__ == "__main__":
    main()
