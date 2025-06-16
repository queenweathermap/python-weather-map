import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
import io

# .envなどで設定済みのものを使用
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
ICLOUD_DESKTOP = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Desktop")

def get_drive_service():
    key_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(key_dict, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=credentials)

def download_latest_image_to_icloud():
    service = get_drive_service()
    # 最新のファイル取得
    results = service.files().list(
        q=f"'{DRIVE_FOLDER_ID}' in parents",
        orderBy="createdTime desc",
        pageSize=1,
        fields="files(id, name)"
    ).execute()
    files = results.get('files', [])
    if not files:
        print("画像ファイルが見つかりません")
        return
    file_id = files[0]['id']
    file_name = files[0]['name']
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(os.path.join(ICLOUD_DESKTOP, file_name), 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    print(f"ダウンロード完了: {file_name}")

if __name__ == "__main__":
    download_latest_image_to_icloud()
