# gpv_panel_daily_akita.py
# ===============================================================
# 秋田局地MSMパネル（エマグラム付き）自動生成スクリプト
# ---------------------------------------------------------------
# ・RISH GPVデータ（MSM）を最新公開分で自動ダウンロード
# ・「存在する最新」ディレクトリ/ファイルを自動判定
# ・GPVファイルがなければサイクル遡りで取得
# ・描画後はGoogle Drive/Slackへ自動通知（既存モジュール利用）
# ---------------------------------------------------------------
# 2025-06-27 by ChatGPT
# ===============================================================

import sys
import traceback
import os
import datetime
import requests

# ---- モジュール読み込み（※既存プロジェクトのまま） ----
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify

# === 定数（環境に応じて変更） ===
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]  # MSMサイクル（遡り探索用）

def find_latest_available_cycle(base_url=BASE_URL, max_days=2):
    """RISHアーカイブ内で、存在する最新の日付・サイクル時刻を返す"""
    now = datetime.datetime.utcnow()
    for day_delta in range(max_days):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = t.strftime("%Y %m %d %H").split()
            url = f"{base_url}/{y}/{m}/{d}/"
            try:
                r = requests.head(url, timeout=5)
            except Exception as e:
                continue
            if r.status_code == 200:
                return y, m, d, hh, url
    raise Exception("最新のGPVサイクルが見つかりませんでした")

def main():
    try:
        # === 最新公開済みGPVサイクルを取得 ===
        y, m, d, hh, data_url = find_latest_available_cycle()
        print(f"[INFO] 最新GPVサイクル: {y}/{m}/{d} {hh}UTC ({data_url})")
        target_init = f"{y}{m}{d}{hh}0000"

        # === 必要なGPVファイル名リスト例（秋田局所）===
        # MSM L-pall/Lsurf等。必要に応じて追加
        file_patterns = [
            f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
            f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin"
        ]
        file_paths = []
        for fname in file_patterns:
            url = f"{data_url}{fname}"
            print(f"[INFO] ダウンロード: {url}")
            resp = requests.get(url)
            if resp.status_code == 200:
                local_path = os.path.join("./data", fname)
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                print(f"[OK] 保存: {local_path}")
                file_paths.append(local_path)
            else:
                print(f"[WARN] ファイル未取得: {url} (status={resp.status_code})")

        if len(file_paths) == 0:
            raise FileNotFoundError("GPVファイルが見つかりません")

        # === 天気図パネル自動描画・通知 ===
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            gpv_files=file_paths,
            init_time=target_init,
            region="akita",
            # その他必要な引数
        )

        print("[OK] 秋田局地パネル生成・通知完了")
        print(f"Drive URL: {drive_url}")

    except Exception as e:
        print(f"[ERROR] {e}")
        traceback.print_exc()
        # Slack等へ異常通知も可
        sys.exit(1)

if __name__ == "__main__":
    main()
