# drive_utils.py
# ===============================================
# Google Drive画像アップロード＆共有リンク発行ユーティリティ
# ===============================================

import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_account.json'  # ダウンロードした認証情報ファイル

def upload_and_share(filepath, folder_id=None):
    """
    Google Driveに画像をアップロードし、共有リンクを返す
    filepath: アップロードする画像ファイルパス
    folder_id: アップロード先フォルダID（省略可）
    戻り値：共有URL(str)
    """
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('drive', 'v3', credentials=credentials)
    file_metadata = {'name': os.path.basename(filepath)}
    if folder_id:
        file_metadata['parents'] = [folder_id]
    media = MediaFileUpload(filepath, mimetype='image/jpeg')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    # 誰でもリンク閲覧可能に
    service.permissions().create(
        fileId=file['id'],
        body={'role': 'reader', 'type': 'anyone'},
    ).execute()
    # 共有リンク取得
    file_url = f"https://drive.google.com/uc?id={file['id']}&export=download"
    return file_url

# 例
if __name__ == "__main__":
    url = upload_and_share('test.jpg', folder_id=None)  # フォルダ未指定ならマイドライブ直下
    print("アップロード&共有リンク：", url)
