# ===============================
# 1. 必要なライブラリインポート
# ===============================
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

# ===============================
# 2. データ取得パターン指定
# ===============================
# 取得したいファイルのパターンを選択（例: GSM日本域0.1度 気圧面 L-pall）
# 他パターンは上記資料/ディレクトリリストを参照して変更可能
GPV_PATTERN = "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin"
BASE_DIR = "./data"
# 必要に応じて "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin" など

# ===============================
# 3. 日付・ディレクトリからファイル名を自動検索
# ===============================
def download_available_gsm_gpv(pattern=GPV_PATTERN, base_dir=BASE_DIR):
    now = datetime.utcnow() + timedelta(hours=9)
    tried = []
    for day_offset in range(0, 2):  # 今日→昨日
        dt = now - timedelta(days=day_offset)
        ymd = dt.strftime("%Y%m%d")
        y = dt.strftime("%Y")
        m = dt.strftime("%m")
        d = dt.strftime("%d")
        for h in [18, 12, 6, 0]:  # 新しい順
            fname = f"Z__C_RJTD_{ymd}{h:02d}0000_{pattern}"
            url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{y}/{m}/{d}/{fname}"
            out_dir = os.path.abspath(base_dir)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, fname)
            tried.append(url)
            try:
                urllib.request.urlretrieve(url, out_path)
                print(f"[OK] GSM GPVダウンロード: {out_path}")
                return out_path, datetime(dt.year, dt.month, dt.day, h)
            except Exception as e:
                print(f"[NG] {url.split('/')[-1]}: {e}")
    print("【ERROR】直近2日間でダウンロードできるファイルが見つかりませんでした。")
    print("試行URL：")
    for t in tried:　　
        print(t)
    return None, None
# ===============================
# 4. 今日/昨日のデータでダウンロードURL自動選択
# ===============================
def download_gsm_gpv(pattern=GPV_PATTERN, out_dir="gpv_data"):
    now = datetime.utcnow() + timedelta(hours=9)  # JSTベース
    for offset in range(0, 2):  # 今日→昨日
        date = now - timedelta(days=offset)
        url = find_gsm_gpv_url(date, pattern)
        if url:
            print(f"ダウンロードURL: {url}")
            os.makedirs(out_dir, exist_ok=True)
            local_file = os.path.join(out_dir, os.path.basename(url))
            # 既存ならスキップ
            if not os.path.exists(local_file):
                urllib.request.urlretrieve(url, local_file)
                print(f"ダウンロード完了: {local_file}")
            else:
                print(f"既にダウンロード済: {local_file}")
            # 初期時刻推定
            ymdhh = os.path.basename(url).split('_')[3]
            init_time = datetime.strptime(ymdhh, "%Y%m%d%H%M%S")
            return local_file, init_time
    raise FileNotFoundError("GPVファイルが見つかりませんでした")

# ===============================
# 5. grib2→nc変換 (wgrib2必須)
# ===============================
def grib2_to_nc(grib2_path):
    grib2_path = Path(grib2_path)
    nc_path = grib2_path.with_suffix(grib2_path.suffix + ".nc")
    if nc_path.exists():
        print(f"既にNetCDF変換済: {nc_path}")
        return nc_path
    cmd = f"/Users/home/miniforge3/envs/met_env/bin/wgrib2 {grib2_path} -netcdf {nc_path}"
    print(f"[INFO] grib2→nc変換: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        raise RuntimeError("grib2→nc変換に失敗しました")
    print(f"[INFO] 変換後NetCDF: {nc_path}")
    return nc_path

# ===============================
# 6. xarrayで開いて初期時刻＋hhラベル付きで天気図描画
# ===============================
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

def plot_simple_panel(nc_path, init_time, save_path="gsm_weather_map.jpg"):
    ds = xr.open_dataset(nc_path)
    times = ds.time.values[:4]
    plt.figure(figsize=(16, 4))
    for col, t in enumerate(times):
        ax = plt.subplot(1, 4, col+1, projection=ccrs.PlateCarree())
        # 例：300hPa高度 (実際は好きな変数を選ぶ)
        if "HGT_100mb" in ds.variables:
            hgt = ds["HGT_100mb"].sel(lev=30000, method="nearest").sel(time=t)
            lon = ds.longitude.values
            lat = ds.latitude.values
            Lon, Lat = np.meshgrid(lon, lat)
            cs = ax.contour(Lon, Lat, hgt, transform=ccrs.PlateCarree())
            ax.coastlines("50m")
        # ラベル例：イニシャル時刻＋hh
        fcst_hour = int((np.datetime64(t) - np.datetime64(init_time)).astype('timedelta64[h]'))
        ax.set_title(f"{init_time:%Y%m%d %HUTC}+{fcst_hour:02d}h")
    plt.suptitle("GSM 300hPa高度パネル（サンプル）")
    plt.savefig(save_path, dpi=200)
    plt.close()
    print(f"→ 画像保存: {save_path}")

# ===============================
# 7. 一括実行セル（ダウンロード→変換→描画まで！）
# ===============================
grib2_path, init_time = download_gsm_gpv()
nc_path = grib2_to_nc(grib2_path)
plot_simple_panel(nc_path, init_time)　
