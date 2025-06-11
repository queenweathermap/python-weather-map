# module/line_utils.py
# ===============================================
# LINE公式アカウント（Messaging API）用 通知ユーティリティ
# -----------------------------------------------
# ・個人LINE/グループLINEに自動でテキスト/画像を送信
# ・画像送信にはGoogle Drive/S3等の「外部公開URL」が必要
# ・複数画像送信やリッチメッセージ拡張も今後対応可能
# -----------------------------------------------
# 必要パッケージ: line-bot-sdk
# pip install line-bot-sdk
# -----------------------------------------------
# 利用例:
#   from module.line_utils import send_line_text, send_line_image, send_line_multi_images
#   send_line_text("本日の天気図ができました")
#   send_line_image("https://your-public-url/tenkizu1.jpg")
#   send_line_multi_images([
#       "https://your-public-url/tenkizu1.jpg",
#       "https://your-public-url/tenkizu2.jpg",
#       "https://your-public-url/tenkizu3.jpg"
#   ])
# ===============================================

import os
from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage

# -- 環境変数からアクセストークン/送信先を取得 --
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
TO_USER_ID = os.environ["LINE_TO_USER_ID"]

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

def send_line_text(text, to_user_id=TO_USER_ID):
    """LINEでテキストメッセージを送信"""
    line_bot_api.push_message(to_user_id, TextSendMessage(text=text))

def send_line_image(image_url, to_user_id=TO_USER_ID):
    """LINEで画像メッセージを送信（公開画像URLのみ対応）"""
    message = ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url
    )
    line_bot_api.push_message(to_user_id, message)

def send_line_multi_images(image_urls, to_user_id=TO_USER_ID):
    """LINEで複数画像を順番に送信"""
    for url in image_urls:
        send_line_image(url, to_user_id)

# ========== 補足 ==========
# - to_user_idはグループIDでもOK（BOTをグループ招待＆権限許可必須）
# - 画像はLINEサーバからHTTPアクセス可能なURLのみ（Drive/S3/公開静的サーバ等）
# - 画像の保存/公開管理はGoogle Driveの「共有リンク」でも運用可能
#   （ただし自動削除はAPI利用か手動となります）
# ==========================
