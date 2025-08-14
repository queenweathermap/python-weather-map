# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/drive_utils.py (stub)
# -----------------------------------------------------------------------------
# Drive を使わない運用のための無害化スタブ。
# 既存コードが import / 呼び出ししても成功扱いで何もしません。
# =============================================================================

from __future__ import annotations
from typing import Optional

def upload_to_drive(file_path: str, folder_id: Optional[str] = None, **kwargs) -> str:
    print(f"[INFO] drive_utils.stub: upload_to_drive skipped: {file_path} (folder_id={folder_id})")
    return "未アップロード"

def delete_old_files_from_drive(folder_id: Optional[str] = None, older_than_days: int = 30, **kwargs) -> int:
    print(f"[INFO] drive_utils.stub: delete_old_files_from_drive skipped: folder_id={folder_id}, days>{older_than_days}")
    return 0
