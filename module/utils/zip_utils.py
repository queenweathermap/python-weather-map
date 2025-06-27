# module/utils/zip_utils.py
# ===========================================
# ZIPファイル生成ユーティリティ
# -------------------------------------------
# 指定した複数ファイルを1つのZIPファイルにまとめて出力する共通関数
# ・ファイルパスのリストを指定するだけで簡単に圧縮
# ・圧縮ファイル名（zip_path）は絶対パス／相対パスどちらでも可
# ・arcnameはZIP内でのファイル名（ディレクトリ構造を除外）
# ・今後の拡張（パスワード付きZIP等）もここに追記可能
# -------------------------------------------
# 使い方例:
#   from module.utils.zip_utils import zip_files
#   file_list = ["./data/xxx.jpg", "./data/yyy.jpg"]
#   zip_path = "./data/myimgs.zip"
#   zip_files(file_list, zip_path)
# ===========================================

import zipfile
import os

def zip_files(file_list, zip_path):
    """
    複数ファイルを1つのZIPファイルにまとめる共通関数

    Parameters
    ----------
    file_list : list of str
        圧縮するファイルのパス一覧。フルパスでも相対パスでも可。
    zip_path : str
        出力するZIPファイルのパス。拡張子「.zip」を含めること。

    Returns
    -------
    zip_path : str
        実際に作成されたZIPファイルのパス（=引数と同じ）

    Notes
    -----
    ・ZIP内のファイル名は全て「arcname=os.path.basename(file)」でフラットに格納されます
    ・ファイルが存在しない場合はエラーになります（try-exceptでカバー可）
    ・大量ファイルの場合も高速です
    """
    # --- ZIPファイル生成処理 ---
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file in file_list:
            # arcname指定でZIP内にはファイル名のみ（ディレクトリ情報除去）
            zipf.write(file, arcname=os.path.basename(file))
    return zip_path
