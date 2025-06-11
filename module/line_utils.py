# module/line_utils.py
# ===============================================
# LINE公式アカウント（Messaging API）用 通知ユーティリティ
# -----------------------------------------------
# ・個人LINEまたはグループにテキスト・画像を自動送信
# ・画像はGoogle DriveやS3等の「公開URL」を送信（LINEサーバから見える必要あり）
# ・将来的に複数画像/スタンプ/リッチ機能も拡張可能
# -----------------------------------------------
# 必要パッケージ: line-bot-sdk
# pip install line-bot-sdk
# -----------------------------------------------
# 利用例:
#   from module.line_utils import send_line_text, send_line_image, send_line_multi_images
#   send_line_text("今日の天気図をお送りします")
#   send_line_image("https://公開画像URL/tenkizu1.jpg")
#   send_line_multi_images([
#       "https://公開画像URL/tenkizu1.jpg",
#       "https://公開画像URL/tenkizu2.jpg",
#       "https://公開画像URL/tenkizu3.jpg"
#   ])
# ===============================================

import os
from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage

# ===============================================
# 環境変数からトークン・送信先ユーザーIDを取得
# - LINE_CHANNEL_ACCESS_TOKEN: LINE公式アカウントのアクセストークン
# - LINE_TO_USER_ID: 送信相手のユーザーIDまたはグループID
#   ※ユーザーIDの取得方法は下部コメント参照
# ===============================================
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
TO_USER_ID = os.environ["LINE_TO_USER_ID"]

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)

# ===============================================
# 1. テキストメッセージ送信
#    - 送信先指定可（デフォルトは環境変数TO_USER_ID）
# ===============================================
def send_line_text(text, to_user_id=TO_USER_ID):
    """
    LINEでテキストメッセージを送信
    :param text: 送信する文字列
    :param to_user_id: ユーザーIDまたはグループID（省略可）
    """
    line_bot_api.push_message(to_user_id, TextSendMessage(text=text))

# ===============================================
# 2. 画像メッセージ送信（単体）
#    - 画像URLはインターネットからアクセスできる必要あり
#    - original_content_url, preview_image_urlは同じでもOK
# ===============================================
def send_line_image(image_url, to_user_id=TO_USER_ID):
    """
    LINEで画像メッセージを送信
    :param image_url: 公開済み画像URL
    :param to_user_id: ユーザーIDまたはグループID（省略可）
    """
    message = ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url
    )
    line_bot_api.push_message(to_user_id, message)

# ===============================================
# 3. 複数画像を順次送信
#    - 画像リストを渡すと順番に送信
# ===============================================
def send_line_multi_images(image_urls, to_user_id=TO_USER_ID):
    """
    LINEで複数画像メッセージを順番に送信
    :param image_urls: 公開済み画像URLのリスト
    :param to_user_id: ユーザーIDまたはグループID（省略可）
    """
    for url in image_urls:
        send_line_image(url, to_user_id)

# ===============================================
# 【補足】ユーザーID/グループIDの取得について
# -----------------------------------------------
# - Messaging APIのテスト送信時は「自分を友だち追加」しWebhook有効化
# - webhookで受信したイベントのsource.user_id などに出現
#   例：Botに「テスト」と話しかけてみてWebhook受信データを確認
# - 管理画面の[チャネル基本設定]→[チャネルシークレット]と一緒に記載
# - グループ送信も同様（source.group_id）
# ===============================================
