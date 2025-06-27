# msm_plot_mslp_jp.py
# ==================================================
# MSM 地上気圧（ヘクトパスカル）日本語タイトル付き可視化サンプル
# --------------------------------------------------
# 必要: pip install matplotlib cartopy cfgrib ipafont
# ==================================================

import os
import urllib.request
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import xarray as xr

# 日本語フォント（IPAGothic）を指定
plt.rcParams['font.family'] = 'IPAGothic'

# MSM GPV Lsurf（地上）GRIB2ファイルURL自動取得
GPV_MIRROR_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
PATTERN = "MSM_GPV_Rjp_Lsurf"
FH = "FH00-15"
date_str = "20250622"  # 必要に応じて日付は動的に
H = "00"

fname = f"Z__C_RJTD_{date_str}{H}0000_{PATTERN}_{FH}_grib2.bin"
y, m, d = date_str[:4], date_str[4:6], date_str[6:8]
url = f"{GPV_MIRROR_URL}/{y}/{m}/{d}/{fname}"
local_path = f"./data/{fname}"

# サンプル: なければDL
if not os.path.exists(local_path):
    print(f"[DL] {url}")
    try:
        os.makedirs("./data", exist_ok=True)
        urllib.request.urlretrieve(url, local_path)
        print(f"[OK] DL: {local_path}")
    except Exception as e:
        print(f"[NG] DL失敗: {e}")

# GRIB2ファイルからデータ展開
ds = xr.open_dataset(local_path, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
# prmsl: [step, lat, lon] の場合が多い
prmsl = ds['prmsl'].isel(step=0) / 100  # hPa換算

# 地図作成
fig = plt.figure(figsize=(9, 8))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.set_extent([120, 150, 22, 48], crs=ccrs.PlateCarree())
ax.coastlines(resolution='50m')
ax.gridlines(draw_labels=True, dms=True, x_inline=False, y_inline=False)

# 等圧線プロット
cs = ax.contour(
    ds.longitude, ds.latitude, prmsl,
    levels=range(960, 1040, 4), colors='k', linewidths=1.6
)

# 日本語タイトル
ax.set_title("MSM 地上気圧（ヘクトパスカル）", fontsize=18, pad=16)

# 等圧線ラベル
ax.clabel(cs, fmt="%d", fontsize=12)

# 枠線追加（必要なら）
for spine in ax.spines.values():
    spine.set_edgecolor('black')
    spine.set_linewidth(2)

plt.tight_layout()
plt.savefig("./data/msm_prmsl_test.jpg", dpi=150)
plt.show()
print("[OK] 保存: ./data/msm_prmsl_test.jpg")
