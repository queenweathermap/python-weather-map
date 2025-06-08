import os
import requests

def send_file_to_slack(image_path, channel="#気象と防災"):
    bot_token = os.environ["SLACK_BOT_TOKEN"]
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
    print(response.status_code, response.text)
