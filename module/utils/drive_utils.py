# module/utils/drive_utils.py
# ===============================================================
# Google Drive API操作ユーティリティ（アップロード・削除）
# ---------------------------------------------------------------
# ・任意ファイルのDriveアップロード＆共有リンク取得（全員閲覧可）
# ・Driveフォルダ内の古いファイル（作成日基準）を自動削除
# ・サービスアカウントを使って認証（.env or Secretsで設定）
# ---------------------------------------------------------------
# 必須環境変数:
#   - GOOGLE_SERVICE_ACCOUNT_JSON: 認証情報JSON（文字列）
#   - DRIVE_FOLDER_ID: デフォルトのアップロード先フォルダID
# ===============================================================

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime, timedelta, timezone

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive_service(creds_json=None):
    """
    Google Drive APIサービスを返す（サービスアカウント認証）
    - creds_json: サービスアカウントJSON（str/dict or Noneで環境変数利用）
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import json, os

    if creds_json:
        if isinstance(creds_json, str):
            info = json.loads(creds_json)
        else:
            info = creds_json
        credentials = service_account.Credentials.from_service_account_info(info)
    else:
        env_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not env_json:
            raise RuntimeError("Google認証情報が環境変数 GOOGLE_SERVICE_ACCOUNT_JSON にありません")
        credentials = service_account.Credentials.from_service_account_info(json.loads(env_json))
    service = build('drive', 'v3', credentials=credentials)
    return service


def upload_to_drive(file_path, folder_id=DRIVE_FOLDER_ID):
    """
    任意ファイルをGoogle Driveにアップロードし、共有リンクを返す
    - file_path: ローカルのアップロード対象ファイルパス
    - folder_id: 保存先フォルダID（省略時は環境変数）
    """
    service = get_drive_service()
    metadata = {"name": os.path.basename(file_path), "parents": [folder_id]}
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(body=metadata, media_body=media, fields="id").execute()
    service.permissions().create(fileId=uploaded["id"], body={"type": "anyone", "role": "reader"}).execute()
    file_id = uploaded["id"]
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    

def delete_old_files_from_drive(folder_id=DRIVE_FOLDER_ID, older_than_days=30, creds_json=None):
    """
    指定フォルダ内の古いファイルを削除（作成日がN日より前）
    - folder_id: 対象フォルダID
    - older_than_days: N日以上前のファイルを削除
    - creds_json: GoogleサービスアカウントのJSON（文字列 or None）
    """
    # creds_jsonが渡された場合はそれを使って認証
    service = get_drive_service(creds_json=creds_json)
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    # RFC3339形式 (例: '2023-06-01T00:00:00+00:00')
    cutoff_str = cutoff.isoformat()
    query = f"'{folder_id}' in parents and trashed = false and createdTime < '{cutoff_str}'"
    results = service.files().list(q=query, fields="files(id, name, createdTime)").execute()
    files = results.get("files", [])
    for f in files:
        print(f"[DELETE] {f['name']} ({f['createdTime']})")
        service.files().delete(fileId=f["id"]).execute()

