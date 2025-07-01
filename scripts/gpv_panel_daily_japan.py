# ===============================================================
# scripts/gpv_panel_daily_japan.py
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Drive+Slack通知バッチ
# 2025-06-30 isobaricInhPaエラー対策「変数・層ごと個別open」完全対応版
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


def open_grib2_var(path, varname, type_of_level=None, level_val=None, stepType=None):
    filter_keys = {}
    if type_of_level:
        filter_keys['typeOfLevel'] = type_of_level
    if level_val is not None:
        filter_keys['isobaricInhPa' if type_of_level == 'isobaric' else 'level'] = level_val
    if stepType:
        filter_keys['stepType'] = stepType

    # まず一発で絞れるかtry
    try:
        ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys=filter_keys)
        return ds[varname] if varname in ds else None
    except Exception as e:
        msg = str(e)
        # 候補リスト例を自動パース
        if "multiple values for unique key" in msg:
            import re
            candidates = re.findall(r"filter_by_keys=({.*?})", msg)
            for cand in candidates:
                import ast
                try:
                    cand_dict = ast.literal_eval(cand)
                    ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys=cand_dict)
                    if varname in ds:
                        print(f"[OK] {varname} found with {cand_dict}")
                        return ds[varname]
                except Exception as e2:
                    continue
        print(f"[WARN] open_grib2_var failed for {varname}: {e}")
        return None


# --- GPVファイルの自動探索＆ダウンロード ---
def find_and_download_gpv_files(
    base_dir="./data",
    days_back=2,
    cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
    fh_band_gsm="FD0000-0100",
    fh_band_msm="FH00-15"
):
    """
    GSMとMSMの最新イニシャル時刻の必要ファイル3種をDL＆返却（パス3つ）
    """
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

# scripts/gpv_panel_daily_japan.py
# --- メインバッチ処理 ---
def main():
    base_dir = "./data"
    output_dir = "./output"
    drive_folder = os.environ.get("DRIVE_FOLDER_ID")
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")
    days_back = 2

    gsm_l_pall_path = None
    msm_l_pall_path = None
    msm_lsurf_path  = None

    try:
        # 1. 必要ファイルDL＆パス取得
        ymd, hh, (gsm_l_pall_path, msm_l_pall_path, msm_lsurf_path) = find_and_download_gpv_files(
            base_dir=base_dir, days_back=days_back
        )


        # 3.地上変数取得部分（例）
        prmsl = open_grib2_var(msm_l_pall_path, "prmsl", "surface", stepType="instant")
        u10   = open_grib2_var(msm_lsurf_path, "u10", "heightAboveGround", 10, stepType="instant")
        v10   = open_grib2_var(msm_lsurf_path, "v10", "heightAboveGround", 10, stepType="instant")
        apcp  = open_grib2_var(msm_lsurf_path, "apcp", "surface", stepType="accum")

        if prmsl is None:
            print("[WARN] prmsl（海面更正気圧）が取得できません")
        if u10 is None:
            print("[WARN] u10（10m風）が取得できません")
        if v10 is None:
            print("[WARN] v10（10m風）が取得できません")
        if apcp is None:
            print("[WARN] apcp（降水量）が取得できません")

        # 変数一覧を見たい場合も個別open
        for var, stype in [("u10", "instant"), ("v10", "instant"), ("apcp", "accum")]:
            try:
                ds = xr.open_dataset(
                    msm_lsurf_path,
                    engine="cfgrib",
                    filter_by_keys={"shortName": var, "stepType": stype}
                )
                print(f"[DEBUG] MSM_Lsurf {var} ({stype}): {list(ds.variables)}")
            except Exception as e:
                print(f"[DEBUG] MSM_Lsurf {var} ({stype}) error:", e)

        # --- 4. パネル用データ辞書を「全部個別open」で作成 ---
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
        
            # MSM（下層）
            "t_850":  open_grib2_var(msm_l_pall_path, "t", "isobaric", 850),
            "u_850":  open_grib2_var(msm_l_pall_path, "u", "isobaric", 850),
            "v_850":  open_grib2_var(msm_l_pall_path, "v", "isobaric", 850),
            "w_700":  open_grib2_var(msm_l_pall_path, "w", "isobaric", 700),
            "r_850":  open_grib2_var(msm_l_pall_path, "r", "isobaric", 850),
        
            # 地上（MSM Lsurfファイル）
            "prmsl": open_grib2_var(msm_lsurf_path, "prmsl", "surface"),
            "u10":   open_grib2_var(msm_lsurf_path, "u10", "heightAboveGround", 10),
            "v10":   open_grib2_var(msm_lsurf_path, "v10", "heightAboveGround", 10),
            "apcp":  open_grib2_var(msm_lsurf_path, "apcp", "surface"),
        }



        # 5. パネル定義取得→描画
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

        # 6. Driveアップロード→Slack通知
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
    except Exception as e:
        send_slack_text(channel=slack_channel, message=f":x: パネル生成失敗: {e}")
        print(f"[ERROR] {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
