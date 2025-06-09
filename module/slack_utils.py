# module/slack_utils.py
import os
from slack_sdk import WebClient

def send_file_to_slack(image_path, channel, initial_comment="天気図をお届けします！"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    client = WebClient(token=bot_token)
    try:
        response = client.files_upload(
            channels=channel,
            file=image_path,
            title=os.path.basename(image_path),
            initial_comment=initial_comment
        )
        print("[Slack送信] status:", response.status_code if hasattr(response, "status_code") else "OK", response)
    except Exception as e:
        print("Error:  Slack送信失敗:", e)
