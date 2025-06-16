# module/utils/line_utils.py
# ===============================================
# LINE公式アカウント（Messaging API）通知ユーティリティ
# -----------------------------------------------
# ・公式LINEに自動でテキスト/画像を送信（Push型・1:1想定）
# ・環境変数でアクセストークン・宛先ユーザーIDを指定
# ・複数画像やリッチメッセージ等も今後拡張しやすい構成
# ・メッセージ送信は各関数単体で使えるシンプル設計
# -----------------------------------------------
# 必要パッケージ:
#   pip install line-bot-sdk
# -----------------------------------------------
# 利用例:
#   send_line_text("本日の天気図ができました")
#   send_line_image("https://your-public-url/tenkizu1.jpg")
#   send_line_multi_images([...])
# -----------------------------------------------
# 2025-06-17 by ChatGPT
# ===============================================

import os
from linebot import LineBotApi
from linebot.models import TextSendMessage, ImageSendMessage

# ------------------------------------------------
# 環境変数から認証情報を取得
# ------------------------------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

# ------------------------------------------------
# LINE Bot API 初期化
# ------------------------------------------------
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

def send_line_text(text, to_user_id=LINE_USER_ID):
    """
    指定ユーザーにLINEテキストメッセージを送信
    """
    # --- 日本語・英語どちらも自動判別（そのまま送信OK）
    line_bot_api.push_message(to_user_id, TextSendMessage(text=text))

def send_line_image(image_url, to_user_id=LINE_USER_ID):
    """
    指定ユーザーにLINE画像メッセージを送信
    image_url: 公開URL必須（LINEサーバから直接取得できるURLのみ）
    """
    message = ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url
    )
    line_bot_api.push_message(to_user_id, message)

def send_line_multi_images(image_urls, to_user_id=LINE_USER_ID):
    """
    指定ユーザーに画像リストを順次送信（10枚まで推奨）
    """
    for url in image_urls:
        send_line_image(url, to_user_id)

# ===============================================
# END OF FILE
# ===============================================

# ---- 補足コメント（日本語多め） ----
# ・LINEの仕様上、画像は必ず「外部公開URL」（Google Drive等は共有URL直リンク可）
# ・push_messageで1:1送信、複数同時送信にはforループで順次
# ・例外処理やログ出力は、実運用時はtry/except等で拡張可能
# ・リッチメニュー・ボタン付きなどは line-bot-sdk の他モデルを利用
