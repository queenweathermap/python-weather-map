# scripts/gpv_panel_daily_japan.py
# ===============================================================
# 全国（GSM+MSMハイブリッド）天気図パネル自動生成・Slack通知スクリプト
# 2025-06-26 ChatGPT 最小雛形リファクタ
# ===============================================================

from module.plotter.gpv_plotter_hybrid import generate_japan_panel_and_notify

if __name__ == "__main__":
    # パラメータだけここで指定（運用時は引数や設定ファイルも可）
    ymd = "20240622"
    hh = "12"
    model = "HYBRID"  # "GSM" or "MSM"でも可
    output_dir = "./data"
    drive_folder = "DRIVE_FOLDER_ID"  # .envで参照でもOK
    ncols = 8        # 1枚に表示する時系列数
    npages = 2       # 2ページ構成なら2

    # 主要ロジックをmodule側に丸投げ
    generate_japan_panel_and_notify(
        ymd=ymd,
        hh=hh,
        model=model,
        output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=ncols,
        npages=npages,
    )
