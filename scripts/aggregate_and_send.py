# -*- coding: utf-8 -*-
"""
scripts/aggregate_and_send.py (split版対応)
matrix/並列ジョブで作った top/bottom 画像を集約して送信。
scripts/aggregate_and_send.py (split版 + Slack 2枚/1投稿)
"""

import os
import sys
import re
import glob
from datetime import datetime

from module.utils.mail_utils import send_mail
from module.utils.zip_utils import zip_files
from module.utils.slack_utils import upload_files_slack  # ★ 追加

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
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")  # ★ これがあればSlackにも投稿

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

    # top / bottom に分離（ファイル名に _top / _bottom が付いている前提）
    tops = [p for p in files if "_top" in os.path.basename(p)]
    bottoms = [p for p in files if "_bottom" in os.path.basename(p)]
    tops.sort(key=lambda s: _natural_key(os.path.basename(s)))
    bottoms.sort(key=lambda s: _natural_key(os.path.basename(s)))

    # 件数整合（多い側に合わせず、ペアにならない分は捨てる）
    pair_count = min(len(tops), len(bottoms))
    paired = list(zip(tops[:pair_count], bottoms[:pair_count]))

    # 件名ラベル抽出
    dt_label = datetime.utcnow().strftime("%Y%m%d UTC%H")
    m = re.search(r"(\d{8})_UTC(\d{2})", " ".join(files))
    if m:
        dt_label = f"{m.group(1)} UTC{m.group(2)}"

    # 並び順（メール添付用）は top全部→bottom全部 の自然順
    def sort_key_mail(p):
        base = os.path.basename(p)
        part = 0 if "_top" in base else 1
        return (part, _natural_key(base))
    files_for_mail = sorted(files, key=sort_key_mail)

    subject = f"{subject_prefix} 全国パネル {dt_label}（top+bottom 合計 {len(files_for_mail)}枚）"

    # 本文
    body_lines = [
        "全国パネルをまとめてお送りします。",
        "",
        "内訳（ファイル名）:",
        *[f" - {os.path.basename(p)}" for p in files_for_mail],
    ]
    body = "\n".join(body_lines)

    # ---- メール送信（ZIP条件付き）----
    total_mb = _human_mb(_total_size(files_for_mail))
    print(f"[INFO] 添付候補 {len(files_for_mail)}件, 合計 {total_mb} MB (limit={max_mb}MB)")
    if must_zip or total_mb > max_mb:
        zip_name = f"japan_panels_{dt_label.replace(' ', '_')}.zip"
        zip_path = os.path.join(base_dir, zip_name)
        zip_files(files_for_mail, zip_path)
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
            attachment_paths=files_for_mail,
            is_html=False,
        )
    print("[DONE] メール送信完了")

    # ---- Slack投稿：2枚/1投稿（top, bottom をセットで）----
    if slack_channel and paired:
        total_pairs = len(paired)
        print(f"[INFO] Slack 投稿: {total_pairs} ペア（2枚/投稿）")
        for i, (pt, pb) in enumerate(paired, start=1):
            comment = f"全国パネル {dt_label}  ペア {i}/{total_pairs}\n" \
                      f"{os.path.basename(pt)} + {os.path.basename(pb)}"
            titles = [os.path.basename(pt), os.path.basename(pb)]
            try:
                upload_files_slack(
                    channel=slack_channel,
                    filepaths=[pt, pb],
                    titles=titles,
                    initial_comment=comment,
                )
            except Exception as e:
                print(f"[WARN] Slack投稿失敗 (pair#{i}): {e}")

    print("[DONE] 集約送信 + Slack投稿 完了")

if __name__ == "__main__":
    main()
