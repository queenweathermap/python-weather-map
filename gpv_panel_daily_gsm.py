# gpv_panel_daily_gsm.py
# ===============================================
# GSMパネル自動生成スクリプト（12時刻×2パターン/日パネル）
# -----------------------------------------------
# ・最新のGSM GPVファイルを12時刻分ダウンロード＆NetCDF変換し、
#   各時刻をパネルとしてまとめて描画（NO DATA時はダミーパネル自動生成）
# ・ファイル/データの欠損や失敗にも強い自動チェック実装
# ・NO DATAの場合は指定時刻リストで強制生成
# -----------------------------------------------
# 2025-06-17 by ChatGPT
# ===============================================

import sys
import traceback
import os
import xarray as xr
import pandas as pd

# --- GPVダウンロード・変換用ユーティリティ ---
from gpv_downloader import (
    find_existing_init_dt, download_gpv_panel, grib2_to_nc,
    GSM_PATTERNS, GPV_MIRROR_URLS
)
# --- パネル生成・NO DATA画像 ---
from module.panel_utils import (
    make_nodata_weather_panel,
    make_daily_weather_panel_multi_time,
    align_datasets_common,
)

BASE_DIR = "./data"
NCOLS = 12
OUTFILE = sys.argv[1] if len(sys.argv) > 1 else "gsm_weather_map.jpg"

def get_gpv_nodata_times(ncols=12):
    """
    GPVイニシャル（00,06,12,18時）基準のNO DATA時刻リストを返す
    """
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    # 直前の「00, 06, 12, 18」時に揃える
    hour = now.hour
    init_hour = max([h for h in [0, 6, 12, 18] if h <= hour])
    base_time = now.replace(hour=init_hour)
    # もし今が0時未満の場合、前日18時を基準にする
    if hour < 0:
        base_time -= pd.Timedelta(days=1)
        base_time = base_time.replace(hour=18)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(ncols)]



if __name__ == "__main__":
    try:
        print("=== GSMパネル処理開始 ===")
        # 1. 最新のイニシャル時刻を探索（GSM: 0時/12時が標準）
        init_dt = find_existing_init_dt(
            GSM_PATTERNS, BASE_DIR, GPV_MIRROR_URLS, hours=[0, 12]
        )
        if init_dt is None:
            print("NO DATA: GSMファイルがサーバに見つかりません")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        print(f"init_dt: {init_dt}")

        # 2. 12時刻×2パターン ダウンロード実行
        panel_files = download_gpv_panel(
            GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=NCOLS
        )
        print("panel_files:", panel_files)

        # 3. 欠損時刻やNone/異常型を除去し、2パターン揃った時刻のみ抽出
        pattern_files = []
        for i, f in enumerate(panel_files):
            if isinstance(f, (list, tuple)) and len(f) == len(GSM_PATTERNS):
                if None not in f:
                    pattern_files.append(f)
                else:
                    print(f"[WARN] panel_files[{i}]にNoneあり: {f}")
            else:
                print(f"[WARN] panel_files[{i}]が異常: {f}")
        print("pattern_files:", pattern_files)

        if not pattern_files or len(pattern_files) < 2:
            print("NO DATA: pattern_files is None or <2")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # flatten時もNoneが来ないようにガード
        file_list = []
        for sublist in pattern_files:
            if isinstance(sublist, (list, tuple)):
                for item in sublist:
                    if item is not None:
                        file_list.append(item)
                    else:
                        print("[WARN] sublist内itemがNone:", sublist)

        print("2. NetCDF変換開始")
        # 4. GRIB2→NetCDF変換（全ファイルを一括処理、失敗・小サイズは除外）
        nc_paths = []
        for path, _ in file_list:
            nc_path = grib2_to_nc(path)
            if nc_path and os.path.exists(nc_path):
                nc_paths.append(nc_path)
            else:
                print(f"[SKIP] NetCDF変換失敗: {nc_path}（元ファイル: {path}）")
        print("nc_paths:", nc_paths)

        if not nc_paths or len(nc_paths) < 2:
            print("NO DATA: ncファイル少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 5. NetCDFからxarray Datasetをリストで取得
        ds_list = []
        for nc in nc_paths:
            try:
                ds = xr.open_dataset(nc)
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] open_dataset失敗: {nc} ({e})")
        if not ds_list or len(ds_list) < 2:
            print("NO DATA: ds_list少なすぎ")
            make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
            sys.exit(0)

        # 6. すべてのDatasetを共通座標にアライン
        ds_list_aligned = align_datasets_common(ds_list)
        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        # time座標→pandas.Timestampリスト化（最大NCOLS本分）
        times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:NCOLS]]

        # 7. パネル画像として描画・保存
        make_daily_weather_panel_multi_time(ds, times, OUTFILE)
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        make_nodata_weather_panel(get_gpv_nodata_times(), save_path=OUTFILE)
        sys.exit(1)
