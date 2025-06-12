# module/drive_utils.py
# ===============================================
# Google Drive自動アップロードユーティリティ（サービスアカウント対応）
# -----------------------------------------------
# ・画像やファイルをGoogle Driveの指定フォルダへ自動アップロード
# ・公開URL（共有リンク）を取得し通知や保存に活用
# ・3日以上前のファイルを自動削除する関数も実装予定
# -----------------------------------------------
# 必要パッケージ:
#   pip install google-api-python-client google-auth-httplib2 google-auth
#   pip install python-dotenv
# -----------------------------------------------
# 利用例:
#   from module.drive_utils import upload_to_drive
#   url = upload_to_drive("weather_map.jpg")
#   print("画像の共有URL:", url)
# ===============================================

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# .envから必要な情報を取得
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]

# サービスアカウント認証
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """
    サービスアカウント情報からDrive APIサービスを生成
    """
    key_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(key_dict, scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)
    return service

def upload_to_drive(file_path, folder_id=DRIVE_FOLDER_ID):
    """
    指定ファイルをGoogle Driveのフォルダにアップロードし、共有URLを返す
    """
    service = get_drive_service()
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    # 共有設定：リンクを知っている全員が閲覧可能
    permission = {'type': 'anyone', 'role': 'reader'}
    service.permissions().create(fileId=uploaded['id'], body=permission).execute()

    file_id = uploaded['id']
    share_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    return share_url

# --- 応用: 古いファイルの自動削除（例・未使用） ---
def delete_old_files(days=3, folder_id=DRIVE_FOLDER_ID):
    """
    指定フォルダ内でdays日以上前のファイルを削除（UTC基準）
    """
    from datetime import datetime, timedelta, timezone
    service = get_drive_service()
    # ファイルリスト取得
    q = f"'{folder_id}' in parents"
    files = service.files().list(q=q, fields="files(id, name, createdTime)").execute().get('files', [])
    now = datetime.now(timezone.utc)
    for f in files:
        created = datetime.fromisoformat(f['createdTime'].replace('Z', '+00:00'))
        if (now - created).days >= days:
            service.files().delete(fileId=f['id']).execute()
            print(f"削除: {f['name']} ({created})")

# --- end ---
