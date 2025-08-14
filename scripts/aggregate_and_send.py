# -*- coding: utf-8 -*-
"""
scripts/aggregate_and_send.py
matrixで作った画像を全部集めて、1通のメールで送信（Slack同報）。
- 既定: 複数画像をそのまま添付
- MAIL_ATTACH_AS_ZIP="1" なら ZIP に固めて 1ファイル添付
"""

import os, glob, re, sys
from datetime import datetime
from module.utils.mail_utils import send_mail
from module.utils.zip_utils import zip_files

def natural_sort_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]

def main():
    base_dir = os.environ.get("AGGREGATE_DIR", "./all_outputs")
    attach_as_zip = os.environ.get("MAIL_ATTACH_AS_ZIP", "0") == "1"
    subject_prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "[Japan]")

    # 画像をすべて収集（拡張子は必要に応じて追加）
    patterns = [
        os.path.join(base_dir, "**", "*.jpg"),
        os.path.join(base_dir, "**", "*.png"),
    ]
    files = []
    for p in patterns:
        files.extend(glob.glob(p, recursive=True))
    files = sorted(set(files), key=natural_sort_key)

    if not files:
        print("[ERROR] 添付対象ファイルがありません")
        sys.exit(1)

    # 件名まとめ（UTC初期時刻などがファイル名に含まれていれば拾う）
    dt_label = datetime.utcnow().strftime("%Y%m%d %HUTC")
    # 例: panel_japan_20250813_UTC00_fh09.jpg から “20250813 UTC00” を拾う
    m = re.search(r'(\d{8})_UTC(\d{2})', " ".join(files))
    if m:
        dt_label = f"{m.group(1)} UTC{m.group(2)}"

    subject = f"{subject_prefix} 全国パネル {dt_label}（{len(files)}枚）"

    # 本文（簡易）
    lines = ["添付に全国パネルをまとめてお送りします。", "", "内訳:"]
    for f in files:
        lines.append(" - " + os.path.basename(f))
    body = "\n".join(lines)

    if attach_as_zip:
        zip_path = os.path.join(base_dir, f"japan_panels_{dt_label.replace(' ', '_')}.zip")
        zip_files(files, zip_path)
        print(f"[OK] ZIP作成: {zip_path}")
        send_mail(
            subject=subject + " [ZIP]",
            body=body,
            attachment_paths=[zip_path],
            is_html=False,
        )
    else:
        # 画像を複数添付（Gmailの上限 ~25MB に注意。今のサイズなら余裕）
        send_mail(
            subject=subject,
            body=body,
            attachment_paths=files,
            is_html=False,
        )
    print("[DONE] 集約送信完了")

if __name__ == "__main__":
    main()
