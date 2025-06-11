import os
import requests

def send_line_message(user_id, message):
    access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }
    res = requests.post(url, headers=headers, json=data)
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
    return res

# 使い方例
# send_line_message("Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "テストメッセージです")
