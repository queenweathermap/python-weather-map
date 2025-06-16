# module/utils/drive_utils.py
# ===============================================
# Google Drive自動アップロードユーティリティ（サービスアカウント対応・英語版）
# -----------------------------------------------
# ・任意の画像やファイルをGoogle Driveの指定フォルダに自動アップロードできます
# ・アップロード直後に「全員に共有可能なURL（リンク）」を取得して返します
# ・管理用途やストレージ圧迫回避のため、「3日以上前の古いファイル自動削除」も関数化済み
# -----------------------------------------------
# 使い方（例）:
#   from module.utils.drive_utils import upload_to_drive
#   url = upload_to_drive("weather_map.jpg")
#   print("Google Drive shareable URL:", url)
# 必須パッケージ:
#   pip install google-api-python-client google-auth-httplib2 google-auth python-dotenv
# ===============================================

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- .envや環境変数から必要情報を取得 ---
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]  # サービスアカウントのJSON文字列
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]  # アップロード先Google DriveフォルダID

# --- Google Drive API認証用のスコープ設定 ---
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """
    サービスアカウント情報からDrive APIサービスインスタンスを生成
    """
    key_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(key_dict, scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)
    return service

def upload_to_drive(file_path, folder_id=DRIVE_FOLDER_ID):
    """
    任意ファイルをGoogle Driveへアップロードし、「全員に共有可能なURL（共有リンク）」を返す関数
    - file_path: アップロードしたいファイル（絶対or相対パス）
    - folder_id: アップロード先DriveフォルダID（デフォルトは環境変数）
    """
    service = get_drive_service()
    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    # --- ファイル本体アップロード ---
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    # --- 共有設定：「リンクを知っている全員が閲覧可能」に変更 ---
    permission = {'type': 'anyone', 'role': 'reader'}
    service.permissions().create(fileId=uploaded['id'], body=permission).execute()

    # --- 共有URL生成 ---
    file_id = uploaded['id']
    share_url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    return share_url

def delete_old_files(days=3, folder_id=DRIVE_FOLDER_ID):
    """
    指定フォルダ内で「days日以上前」に作られた古いファイルを自動削除します（UTC基準）
    - 管理目的やストレージ節約用。実運用では要確認の上ご利用ください。
    """
    from datetime import datetime, timezone
    service = get_drive_service()
    # --- 対象フォルダ内のファイルリスト取得 ---
    q = f"'{folder_id}' in parents"
    files = service.files().list(q=q, fields="files(id, name, createdTime)").execute().get('files', [])
    now = datetime.now(timezone.utc)
    for f in files:
        created = datetime.fromisoformat(f['createdTime'].replace('Z', '+00:00'))
        file_age = (now - created).days
        if file_age >= days:
            service.files().delete(fileId=f['id']).execute()
            print(f"[INFO] Deleted old file: {f['name']} ({created})")

# --- end ---
