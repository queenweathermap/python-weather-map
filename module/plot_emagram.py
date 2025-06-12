# ===============================================
# module/plot_emagram.py
# エマグラム（気温・露点温度・風）描画モジュール
# GSM/MSM両対応＋任意地点指定
# -----------------------------------------------
# 利用例:
#   from module.plot_emagram import plot_emagram_gsm
#   fig, ax = plt.subplots(figsize=(5,7))
#   plot_emagram_gsm(ax, ds, lat=39.72, lon=140.10)  # 秋田
#   plt.show()
# ===============================================

import numpy as np
import matplotlib.pyplot as plt

def extract_profile(ds, lat, lon):
    # 最近傍グリッド抽出
    lat_arr = ds["latitude"].values
    lon_arr = ds["longitude"].values
    ilat = np.abs(lat_arr - lat).argmin()
    ilon = np.abs(lon_arr - lon).argmin()
    # 各層プロファイル抽出（時間次元ありの場合は先頭時刻で抜粋）
    levels = []
    temp = []
    dew = []
    u = []
    v = []
    for var in ds.variables:
        if var.startswith("TMP_") and "surface" not in var:
            lev = int(var.split("_")[1].replace("mb", ""))
            levels.append(lev)
            temp.append(ds[var][0, ilat, ilon] - 273.15)
            dewvar = "DPT_" + var.split("_")[1]
            if dewvar in ds.variables:
                dew.append(ds[dewvar][0, ilat, ilon] - 273.15)
            else:
                dew.append(np.nan)
            uvar = "UGRD_" + var.split("_")[1]
            vvar = "VGRD_" + var.split("_")[1]
            u.append(ds[uvar][0, ilat, ilon] if uvar in ds.variables else np.nan)
            v.append(ds[vvar][0, ilat, ilon] if vvar in ds.variables else np.nan)
    # 高度（気圧）降順にソート
    idx = np.argsort(levels)[::-1]
    return np.array(levels)[idx], np.array(temp)[idx], np.array(dew)[idx], np.array(u)[idx], np.array(v)[idx]

def plot_emagram(ax, ds, lat, lon, model="GSM"):
    levels, temp, dew, u, v = extract_profile(ds, lat, lon)
    # エマグラム枠・気温
    ax.semilogy(temp, levels, 'r', label='Temp')
    ax.semilogy(dew, levels, 'g', label='Dew point')
    ax.invert_yaxis()
    ax.set_ylim(1050, 100)
    ax.set_xlim(-40, 40)
    ax.set_xlabel('Temperature [°C]')
    ax.set_ylabel('Pressure [hPa]')
    ax.grid(True)
    ax.set_title(f"Emagram ({lat:.2f}, {lon:.2f}) {model}")

def plot_emagram_gsm(ax, ds, lat=39.72, lon=140.10):
    return plot_emagram(ax, ds, lat, lon, model="GSM")

def plot_emagram_msm(ax, ds, lat=39.72, lon=140.10):
    return plot_emagram(ax, ds, lat, lon, model="MSM")

# ===============================================
# END OF FILE
# ===============================================
