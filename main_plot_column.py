# main_plot_column.py
# ===============================================
# MSM日本全域・天気図6種を1枚の縦長画像に並べて保存
# ===============================================

import os
import datetime
import matplotlib.pyplot as plt
import xarray as xr

from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot_surface_pressure_wind_precip import plot_surface_pressure_wind_precip

def main():
    # 1. GRIB2ファイル → xarrayで読み込み（例: 975hPaが含まれるMSM L-pall）
    fname = "Z__C_RJTD_20240622120000_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin"
    ds = xr.open_dataset(fname, engine='cfgrib')

    # 2. 縦6行（横1列）のFigure生成
    fig, axes = plt.subplots(nrows=6, ncols=1, figsize=(8, 48), constrained_layout=True)
    fig.suptitle("MSM日本全域 天気図6種", fontsize=22)

    # 3. 各サブプロットにプロット関数を呼び出す
    plot_700hpa_dindex_500hpa_temp(axes[0], ds)
    axes[0].set_title("700hPa D-index / 500hPa 気温")
    
    plot_850hpa_temp_wind_700hpa_w(axes[1], ds)
    axes[1].set_title("850hPa気温・風 + 700hPa鉛直流")
    
    plot_850hpa_thetae_stream(axes[2], ds)
    axes[2].set_title("850hPa θe + Stream")
    
    plot_975hpa_temp_wind_dindex(axes[3], ds)
    axes[3].set_title("975hPa気温・風・D-index")
    
    plot_925hpa_temp_wind_dindex(axes[4], ds)
    axes[4].set_title("925hPa気温・風・D-index")
    
    plot_surface_pressure_wind_precip(axes[5], ds)
    axes[5].set_title("地上: 等圧線・風・降水")

    # 4. 保存
    out_path = f"data/msm_column_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.jpg"
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[OK] Saved: {out_path}")

if __name__ == "__main__":
    main()
