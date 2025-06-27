# module/plot/plot_utils.py
# ===========================================
# matplotlibの日本語フォント設定＆共通地図描画関数
# ===========================================

import matplotlib.pyplot as plt
import cartopy.crs as ccrs

def set_japanese_font(fontname="IPAexGothic"):
    """
    matplotlibの全描画を指定日本語フォントに強制設定する
    """
    plt.rcParams['font.family'] = fontname

def plot_no_data_japan_map(ax, title="NO DATA", fontsize=14):
    """
    データがない時用の地図＋NO DATA表示
    - ax: matplotlib.axes
    - title: サブプロットタイトル
    """
    # 日本域（120E-150E, 20N-50N）に固定
    ax.set_extent([120, 150, 20, 50], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="10m")
    # タイトル（ここは日本語・英語どちらも可）
    ax.set_title(title, fontsize=10)
    # 中央にNO DATA表示
    ax.text(
        0.5, 0.5, "NO DATA",
        ha='center', va='center',
        fontsize=fontsize, color='gray', alpha=0.7,
        transform=ax.transAxes
    )
