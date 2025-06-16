# module/panel_utils.py
# ===============================================
# 天気図パネル作成ユーティリティ（GSM/MSM/局地共通）
# 2025-06-13 by ChatGPT
# ===============================================

import os
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr

# --- 日本語フォント（IPAGothic）強制指定 ---
plt.rcParams['font.family'] = 'IPAGothic'

from module.utils.xr_utils import align_datasets_common


def make_nodata_weather_panel(times, save_path="nodata_panel.jpg", title="NO DATA"):
    """
    データ欠損時用のNO DATAパネル画像を生成
    times: リスト型（表示だけ）
    save_path: 保存ファイル名
    title: 上部タイトル
    """
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.axis("off")
    msg = f"{title}\n\nデータが取得できませんでした。\n\n"
    msg += "\n".join([str(t) for t in times])
    ax.text(0.5, 0.5, msg, fontsize=20, ha="center", va="center", wrap=True)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[NO DATAパネル] {save_path} を出力しました")

def make_local_weather_panel(
    ds, times, save_path,
    pin_lat, pin_lon, city_name,
    lat_range=None, lon_range=None,  # 必要ならエリア範囲指定
    plot_func_list=None,
    nrows=6, ncols=12
):
    """
    指定した地点（緯度経度・地名）＋任意範囲のローカル天気図・エマグラム付きパネルを作成
    """
    import numpy as np
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    fig = plt.figure(figsize=(ncols * 2.5, nrows * 3.5))
    axes = np.empty((nrows, ncols), dtype=object)
    for row in range(1, nrows):
        for col in range(ncols):
            axes[row, col] = fig.add_subplot(nrows, ncols, row * ncols + col + 1, projection=ccrs.PlateCarree())

    # ラベル等
    init_time = pd.Timestamp(times[0])
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # 各時刻ごと
    for col, time in enumerate(times):
        if pd.to_datetime(time) not in pd.to_datetime(ds.time.values):
            for row in range(nrows):
                ax = axes[row, col] if row > 0 else None
                if ax is not None:
                    ax.set_facecolor("white")
                    ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
            continue

        # ピンポイント（エマグラム用）
        dsi_point = ds.sel(latitude=pin_lat, longitude=pin_lon, time=time, method='nearest')
        if plot_func_list:
            plot_func_list[0](fig, col, dsi_point, pin_lat, pin_lon, city_name, nrows, ncols)
        # 範囲抽出（市区町村用）
        if lat_range and lon_range:
            dsi = ds.sel(
                latitude=slice(*lat_range),
                longitude=slice(*lon_range),
                time=time
            )
        else:
            dsi = ds.sel(time=time)
        # 2行目以降の描画関数
        if plot_func_list:
            for row, func in enumerate(plot_func_list[1:], 1):
                func(axes[row, col], dsi)

    for row in range(1, nrows):
        for col in range(ncols):
            ax = axes[row, col]
            gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
            gl.top_labels = False
            gl.right_labels = False

    fig.suptitle(
        f"【{city_name} 局地】天気図パネル（エマグラム含む）\nInit: {init_time.strftime('%Y%m%d %HUTC')} | Forecasts: {', '.join(hh_labels)}",
        fontsize=12, y=1.02
    )
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))


def make_daily_weather_panel_multi_time(ds, times, save_path="weather_panel.jpg", plot_func_list=None, nrows=6, ncols=12):
    """
    1日複数時刻パネルをまとめて描画（メインルーチン）
    ds: xarray.Dataset
    times: 対象時刻配列
    save_path: 出力ファイル名
    plot_func_list: [func, ...] 各段ごとの描画関数リスト（省略時は全パネルグレー）
    nrows, ncols: パネルグリッド数
    """
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 2.5, nrows * 2.2), constrained_layout=True)
    axes = axes.flatten() if isinstance(axes, np.ndarray) else [axes]

    for idx, t in enumerate(times):
        ax = axes[idx]
        ax.set_axis_off()
        # 描画関数リストがあればそれを利用（plot_func_list[行番号](ax, ds, t, ...)）
        if plot_func_list and idx < len(plot_func_list):
            try:
                plot_func_list[idx](ax, ds, t)
            except Exception as e:
                ax.text(0.5, 0.5, "描画エラー", fontsize=10, ha="center", va="center")
        else:
            ax.set_facecolor("lightgray")
            ax.text(0.5, 0.5, "NO DATA", fontsize=16, ha="center", va="center")
        ax.set_title(str(t))

    # 余ったパネルは非表示
    for i in range(len(times), len(axes)):
        axes[i].set_axis_off()
    fig.suptitle("Weather Panel", fontsize=22)
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[天気図パネル] {save_path} を出力しました")

# align_datasets_commonはxr_utilsからimport
# __all__ を使って明示公開
__all__ = [
    "make_nodata_weather_panel",
    "make_daily_weather_panel_multi_time",
    "align_datasets_common",
]

