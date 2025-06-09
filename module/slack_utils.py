import os
import requests

def send_file_to_slack(image_path, channel="C08988S0SRY"):
    """
    指定画像をSlackチャンネル（ID指定推奨）に送信
    環境変数 SLACK_BOT_TOKEN 必須
    """
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        print("[ERROR] SLACK_BOT_TOKEN が環境変数にありません")
        return
    url = "https://slack.com/api/files.upload"
    with open(image_path, "rb") as file_content:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {bot_token}"},
            data={
                "channels": channel,
                "initial_comment": "天気図をお届けします！"
            },
            files={"file": file_content},
        )
    print("[Slack送信] status:", response.status_code, response.text)
    # エラー時追加ログ
    if not response.ok or not response.json().get("ok", False):
        print("[ERROR] Slack送信失敗:", response.text)
