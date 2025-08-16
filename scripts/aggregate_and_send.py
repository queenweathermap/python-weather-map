# -*- coding: utf-8 -*-
"""
scripts/aggregate_and_send.py (split版対応)
matrix/並列ジョブで作った top/bottom 画像を集約して送信。
"""

import os
import sys
import re
import glob
from datetime import datetime

from module.utils.mail_utils import send_mail
from module.utils.zip_utils import zip_files


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _human_mb(bytes_: int) -> float:
    return round(bytes_ / (1024 * 1024), 2)


def _total_size(paths):
    return sum(os.path.getsize(p) for p in paths if os.path.exists(p))


def main():
    base_dir = os.environ.get("AGGREGATE_DIR", "./all_outputs")
    subject_prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "[Japan]").strip()
    must_zip = os.environ.get("MAIL_ATTACH_AS_ZIP", "0") == "1"
    max_mb = float(os.environ.get("MAX_MAIL_SIZE_MB", "20"))

    # 画像収集
    patterns = [
        os.path.join(base_dir, "**", "*.jpg"),
        os.path.join(base_dir, "**", "*.jpeg"),
        os.path.join(base_dir, "**", "*.png"),
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat, recursive=True))
    files = sorted(set(files))

    if not files:
        print(f"[ERROR] 添付対象がありません: {base_dir}")
        sys.exit(1)

    # 並び替え: top → bottom, かつ自然順序
    def sort_key(p):
        base = os.path.basename(p)
        part = 0 if "_top" in base else 1
        return (part, _natural_key(base))

    files = sorted(files, key=sort_key)

    # 件名ラベル抽出
    dt_label = datetime.utcnow().strftime("%Y%m%d UTC%H")
    m = re.search(r"(\d{8})_UTC(\d{2})", " ".join(files))
    if m:
        dt_label = f"{m.group(1)} UTC{m.group(2)}"

    subject = f"{subject_prefix} 全国パネル {dt_label}（top+bottom 合計 {len(files)}枚）"

    # 本文
    body_lines = [
        "全国パネルをまとめてお送りします。",
        "",
        "内訳（ファイル名）:",
        *[f" - {os.path.basename(p)}" for p in files],
    ]
    body = "\n".join(body_lines)

    # サイズチェック
    total_mb = _human_mb(_total_size(files))
    print(f"[INFO] 添付候補 {len(files)}件, 合計 {total_mb} MB (limit={max_mb}MB)")

    if must_zip or total_mb > max_mb:
        zip_name = f"japan_panels_{dt_label.replace(' ', '_')}.zip"
        zip_path = os.path.join(base_dir, zip_name)
        zip_files(files, zip_path)
        print(f"[OK] ZIP作成: {zip_path} ({_human_mb(os.path.getsize(zip_path))} MB)")
        send_mail(
            subject=subject + " [ZIP]",
            body=body,
            attachment_paths=[zip_path],
            is_html=False,
        )
    else:
        send_mail(
            subject=subject,
            body=body,
            attachment_paths=files,
            is_html=False,
        )
    print("[DONE] 集約送信完了")


if __name__ == "__main__":
    main()
