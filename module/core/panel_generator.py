# module/core/panel_generator.py
# ===============================================
# 天気図パネル生成ユーティリティ（axes配列→各plot_xxx実行）
# パネル画像レイアウト生成
# 2025-06-27 by ChatGPT
# ===============================================
import matplotlib.pyplot as plt

def generate_panel(ds, plot_funcs, nrows, ncols, figsize, title=None, step_axis="col", **kwargs):
    """
    汎用パネル生成
      ds: xarray.Dataset
      plot_funcs: [plot_foo, plot_bar, ...]（縦方向順）
      nrows, ncols: パネル行数・列数
      figsize: (W, H)
      step_axis: "col"→横=時系列, "row"→縦=時系列
    """
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize,
                             constrained_layout=True, subplot_kw=dict(projection=kwargs.get("proj", None)))
    if title:
        fig.suptitle(title, fontsize=18)
    
    # step数の上限（step軸があればそれを使う）
    n_steps = ds.dims["step"] if "step" in ds.dims else 1

    for r, plot_func in enumerate(plot_funcs):
        for c in range(ncols):
            step = c if step_axis == "col" else r
            ax = axes[r, c] if nrows > 1 else axes[c]
            # --- ガード追加（stepの範囲を超えたら非表示）---
            if step >= n_steps:
                ax.axis("off")
                continue
            ds_step = ds.isel(step=step) if "step" in ds.dims else ds
            plot_func(ax, ds_step)
    return fig, axes
