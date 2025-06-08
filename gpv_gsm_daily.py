#!/usr/bin/env python
# coding: utf-8

# # GPV天気図（GSM用）

# In[1]:


# ===============================
# 1. 必須ライブラリのimport
# ===============================
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import xarray as xr
import numpy as np
import subprocess
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import pandas as pd
import cartopy.crs as ccrs
import matplotlib.font_manager as fm

# --- 日本語フォント設定（例：游ゴシック） ---
font_path = '/System/Library/AssetsV2/com_apple_MobileAsset_Font7/54ef167d6c8e99a69a0d41ce252cc5995ba47580.asset/AssetData/YuGothic-Medium.otf'
prop = fm.FontProperties(fname=font_path)
plt.rcParams['font.family'] = fm.FontProperties(fname=font_path).get_name()


# 利用可能なフォント一覧から手元の確認がしたい場合
for f in fm.findSystemFonts():
    if "YuGothic" in f or "Yu Gothic" in f or "Gothic" in f or "Toppan Bunkyu Gothic" in f:
        print(f)

# 使いたい関数だけimportしておく（どれだけ増えてもOK）
# from module.plot_300hpa import plot_300hpa_height_wind
from module.plot_500hpa_vorticity import plot_500hpa_vorticity
from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind

# ★ここで5段の描画関数を切り替え可能に！（好きな順、好きな段数）
panel_funcs = [
    # plot_300hpa_height_wind,      # 300hPa
    plot_500hpa_vorticity,          # 500hPa渦度（例）
    plot_700hpa_dindex_500hpa_temp,  # 700湿数・500温度
    plot_850hpa_temp_wind_700hpa_w,  # 850hPa温度・風
    plot_850hpa_thetae_stream,       # 850hPa相当温位
    plot_surface_pressure_and_wind,  # 地上
]

# ===============================
# 2. データ取得・変換・連結
# ===============================

# ダウンロードしたGRIB2/NetCDFファイルの保存先
BASE_DIR = os.path.expanduser("~/Desktop")
os.makedirs(BASE_DIR, exist_ok=True)

# 欲しいファイルパターン一覧（気圧面＋地上）
GSM_PATTERN_LIST = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",   # 気圧面
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",    # 地上
]

def download_available_gsm_gpv(pattern, base_dir):
    """
    サーバ上で最新のGSM GPVファイルを探してDLする。
    """
    now = datetime.utcnow() + timedelta(hours=9)
    tried = []
    for day_offset in range(0, 2):  # 今日→昨日
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y = dt.strftime("%Y")
        m = dt.strftime("%m")
        d = dt.strftime("%d")
        for h in [18, 12, 6, 0]:
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{y}/{m}/{d}/{fname}"
            out_path = os.path.join(base_dir, fname)
            tried.append(url)
            try:
                print(f"[TRY] {url}")
                urllib.request.urlretrieve(url, out_path)
                print(f"[OK] ダウンロード成功: {out_path}")
                return out_path, datetime(dt.year, dt.month, dt.day, h)
            except Exception as e:
                print(f"[NG] {url.split('/')[-1]}: {e}")
    print("【ERROR】ダウンロードできず")
    print("試行URL：")
    for t in tried:
        print(t)
    return None, None

def grib2_to_nc(grib2_path):
    """
    GRIB2→NetCDF（wgrib2利用、パスは各自環境に合わせて変更）
    """
    grib2_path = Path(grib2_path)
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    cmd = f"/Users/home/miniforge3/envs/met_env/bin/wgrib2 {grib2_path} -netcdf {nc_path}"
    print(f"[INFO] grib2→nc変換: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        raise RuntimeError("grib2→nc変換に失敗しました")
    print(f"[OK] 変換後NetCDF: {nc_path}")
    return nc_path

# DL→変換→パスリスト作成
nc_paths = []
downloaded_files = []
for pattern in GSM_PATTERN_LIST:
    grib2_path, init_time = download_available_gsm_gpv(pattern, base_dir=BASE_DIR)
    if grib2_path is not None:
        nc_path = grib2_to_nc(grib2_path)
        nc_paths.append(str(nc_path))
        downloaded_files.extend([grib2_path, nc_path])

if len(nc_paths) < 2:
    raise RuntimeError("気圧面・地上のGRIB2ファイルが両方必要です")

# L-pall, Lsurf に分けてopen
nc_l_pall = [p for p in nc_paths if "L-pall" in p][0]
nc_lsurf  = [p for p in nc_paths if "Lsurf"  in p][0]
ds_l_pall = xr.open_dataset(nc_l_pall)
ds_lsurf  = xr.open_dataset(nc_lsurf)

# mergeして全部入りに
ds = xr.merge([ds_l_pall, ds_lsurf])

# ===============================
# 3. パネル描画関数（描画関数リスト対応・n段可変版）
# ===============================

def add_gridlines(ax):
    """緯度経度グリッド線を追加"""
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_daily_weather_panel_multi_time(ds, times, save_path, panel_funcs, prop=prop):
    """
    1日n時刻×N段の天気図パネルを描画し、1枚画像で保存
    panel_funcs: 各段に使う描画関数（リスト）
    """
    nrows = len(panel_funcs)    # 段数は描画関数リストに合わせて自動可変
    ncols = len(times)
    figsize = (4 * ncols, 3.6 * nrows)
    fig, axes = plt.subplots(
        nrows=nrows, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    # axes shape調整
    if axes.ndim == 1:
        axes = axes.reshape((nrows, 1))
    elif axes.shape[0] != nrows:
        axes = axes.reshape((nrows, -1))

    # ラベル準備
    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels = []
    hh_labels = []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # 各パネル描画（row:段番号, col:時刻）
    for col, time in enumerate(times):
        dsi = ds.sel(time=time)
        for row, func in enumerate(panel_funcs):
            func(axes[row, col], dsi)
        # 最下段だけ時刻ラベル
        axes[-1, col].text(
            0.5, -0.18, col_labels[col], fontsize=9,
            ha='center', va='top', transform=axes[-1, col].transAxes
        )

    # 全パネル緯度・経度線
    for ax in axes.flatten():
        add_gridlines(ax)

    # パネル全体タイトル
    fig.suptitle(
        f"GSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)


# ===============================
# 4. パネル作成・Notebook上で画像表示
# ===============================
wanted_hours = [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33]
all_times = ds.time.values
pd_times = [pd.Timestamp(t) for t in all_times]
init_time = pd_times[0] if pd_times else None
target_times = [t for t in pd_times if t.hour in wanted_hours][:12]

save_path = Path(BASE_DIR) / f"weather_panel_{init_time:%Y%m%d}_12x{len(panel_funcs)}.jpg"
make_daily_weather_panel_multi_time(ds, target_times, save_path, panel_funcs)  # ← panel_funcsを渡す
print(f"✅ {save_path} 保存完了")


# ===============================
# 5. DLファイルの自動削除
# ===============================
for p in downloaded_files:
    try:
        os.remove(p)
        print(f"[CLEANUP] 削除しました: {p}")
    except Exception as e:
        print(f"[CLEANUP] 削除失敗: {p}, {e}")


# In[ ]:





# In[ ]:




