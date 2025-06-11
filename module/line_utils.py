import os
from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage

CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
TO_USER_ID = os.environ["LINE_TO_USER_ID"]

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

def send_line_text(text, to_user_id=TO_USER_ID):
    line_bot_api.push_message(to_user_id, TextSendMessage(text=text))

def send_line_image(image_url, to_user_id=TO_USER_ID):
    message = ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url
    )
    line_bot_api.push_message(to_user_id, message)

def send_line_multi_images(image_urls, to_user_id=TO_USER_ID):
    # 画像3枚を順番に送信
    for url in image_urls:
        send_line_image(url, to_user_id)
