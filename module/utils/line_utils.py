# module/utils/line_utils.py
# ===============================================
# LINE公式アカウント（Messaging API）用 通知ユーティリティ
# -----------------------------------------------
# ・公式LINEに自動でテキスト
# ・画像はDesktop保存
# ・複数画像送信やリッチメッセージ拡張も今後対応可能
# -----------------------------------------------
# 必要パッケージ: line-bot-sdk
# pip install line-bot-sdk
# -----------------------------------------------
# 利用例:
#   send_line_text("本日の天気図ができました")
#   send_line_image("https://your-public-url/tenkizu1.jpg")
# ===============================================

import os
from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage

# 環境変数を正しく読み込み
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

# LINE API設定（修正済み）
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

def send_line_text(text, to_user_id=LINE_USER_ID):
    """
    LINEでテキストメッセージを送信
    """
    line_bot_api.push_message(to_user_id, TextSendMessage(text=text))

def send_line_image(image_url, to_user_id=LINE_USER_ID):
    """
    LINEで画像メッセージを送信
    """
    message = ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url
    )
    line_bot_api.push_message(to_user_id, message)

def send_line_multi_images(image_urls, to_user_id=LINE_USER_ID):
    """
    LINEで複数画像を順次送信
    """
    for url in image_urls:
        send_line_image(url, to_user_id)
