"""デコード済みTEMPからStüve線図(p^0.286 vs T)を描く。matplotlib/numpyのみ。

plot_stuve(levels, title, out_path, unit="kt")
levels は temp_decode.decode_text の levels(辞書のリスト)。
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

K = 0.286
P_BOT, P_TOP = 1050.0, 100.0
T_MIN, T_MAX = -90, 40


_CJK_DONE = False


def use_cjk_font():
    """利用可能な日本語フォントを matplotlib に設定する(mac/Actionsのubuntu両対応)。"""
    global _CJK_DONE
    if _CJK_DONE:
        return
    from matplotlib import font_manager as fm
    names = {f.name for f in fm.fontManager.ttflist}
    for c in ("Hiragino Sans", "Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic"):
        if c in names:
            matplotlib.rcParams["font.family"] = c
            break
    _CJK_DONE = True


def _y(p):
    return np.asarray(p, dtype=float) ** K


def profile(levels):
    """気圧降順の (p, t, td) と風 (p, dir, spd) に整える。同一気圧は後勝ち。"""
    th = {}
    for l in levels:
        if l.get("t") is not None and l["p"] >= P_TOP * 0.9:
            th[round(l["p"], 1)] = (l["t"], l.get("td"))
    wd = {}
    for l in levels:
        if l.get("dir") is not None and l.get("spd") is not None and l["p"] >= P_TOP * 0.9:
            wd[round(l["p"], 1)] = (l["dir"], l["spd"])
    P = sorted(th, reverse=True)
    tprof = [(p, th[p][0], th[p][1]) for p in P]
    wprof, last = [], None
    for p in sorted(wd, reverse=True):  # 矢羽根が重ならないよう気圧の対数で間引く
        if last is None or abs(np.log(last) - np.log(p)) > 0.045:
            wprof.append((p,) + wd[p])
            last = p
    return tprof, wprof


def plot_stuve(levels, title, out_path, unit="kt"):
    use_cjk_font()
    tprof, wprof = profile(levels)
    fig = plt.figure(figsize=(5.2, 6.4), dpi=150)
    ax = fig.add_axes([0.1, 0.07, 0.78, 0.84])
    ax.set_xlim(T_MIN, T_MAX)
    ax.set_ylim(_y(P_BOT), _y(P_TOP))
    ticks = [1000, 900, 800, 700, 600, 500, 400, 300, 200, 100]
    ax.set_yticks(_y(ticks))
    ax.set_yticklabels([str(t) for t in ticks], fontsize=7)
    ax.tick_params(axis="x", labelsize=7)
    ax.set_xticks(range(T_MIN, T_MAX + 1, 10))
    ax.grid(True, color="#bbbbbb", lw=0.4)
    pp = np.linspace(P_BOT, P_TOP, 50)
    # 乾燥断熱線(Stüveでは直線): T = theta*(p/1000)^K - 273.15, 10K刻み
    for th in range(250, 460, 10):
        ax.plot(th * (pp / 1000.0) ** K - 273.15, _y(pp), color="#d8a0a0", lw=0.5, ls="--")
    # 等温線 -0℃ を強調
    ax.axvline(0, color="#7aa0d8", lw=0.8)
    if tprof:
        p = np.array([a[0] for a in tprof])
        t = np.array([a[1] for a in tprof])
        ax.plot(t, _y(p), color="#d62728", lw=1.8, label="気温")
        pd = np.array([a[0] for a in tprof if a[2] is not None])
        td = np.array([a[2] for a in tprof if a[2] is not None])
        # 露点は連続して報じられる範囲だけ線で結ぶ(湿度打ち切り以降は描かない)
        if len(pd):
            ax.plot(td, _y(pd), color="#1f77b4", lw=1.8, label="露点")
    if wprof:
        wp = np.array([a[0] for a in wprof])
        d = np.radians([a[1] for a in wprof])
        s = np.array([a[2] for a in wprof], dtype=float)
        if unit == "m/s":
            s = s * 1.94384  # barbはknot
        u = -s * np.sin(d)
        v = -s * np.cos(d)
        ax2 = ax.twinx()
        ax2.set_ylim(ax.get_ylim())
        ax2.set_yticks([])
        ax2.barbs(np.full(len(wp), 1.03), _y(wp), u, v, length=5.5, lw=0.6,
                  transform=ax2.get_yaxis_transform(), clip_on=False)
    ax.set_xlabel("気温 (℃)", fontsize=8)
    ax.set_ylabel("気圧 (hPa)", fontsize=8)
    fig.text(0.1, 0.945, title, fontsize=10, fontweight="bold")
    ax.legend(loc="upper left", fontsize=7, frameon=False)
    fig.savefig(out_path, format="png")
    plt.close(fig)
