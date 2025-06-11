import os
import requests

def send_line_image(user_id, image_path, preview_path=None):
    access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    # 画像をアップロードして外部URLにする必要あり（ローカルパスは不可）
    # ここではファイルをimgur等にアップロードして取得したURLを使う想定
    image_url = image_path      # 公開URLを指定
    preview_url = preview_path if preview_path else image_url
    data = {
        "to": user_id,
        "messages": [
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": preview_url,
            }
        ]
    }
    res = requests.post(url, headers=headers, json=data)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
    return res

def send_line_images(user_id, image_url_list):
    for url in image_url_list:
        send_line_image(user_id, url)

# 例: 3枚送信
# send_line_images(
#     os.environ["LINE_USER_ID"],
#     [
#         "https://your-server.com/gsm_weather_map.jpg",
#         "https://your-server.com/msm_weather_map.jpg",
#         "https://your-server.com/akita_local_msm_map.jpg",
#     ]
# )
