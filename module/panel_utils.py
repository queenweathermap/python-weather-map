# module/panel_utils.py
# ===============================================
# 天気図パネル作成ユーティリティ（GSM/MSM/局地共通）
# 2025-06-13 by ChatGPT
# ===============================================

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr

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

