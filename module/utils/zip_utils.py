# -*- coding: utf-8 -*-
# =============================================================================
# module/utils/zip_utils.py
# -----------------------------------------------------------------------------
# 目的:
#   - ファイル/ディレクトリを ZIP にまとめるユーティリティ群
#   - ディスク出力型（zip_files / zip_dir）と、メモリ出力型（to_zip_bytes_*）を提供
#
# 特徴:
#   - 圧縮形式: ZIP_DEFLATED（zlib）を既定、圧縮レベル指定可
#   - ZIP 内パスは再現/フラットの両方に対応（引数で制御）
#   - メモリ上で ZIP を完結させる BytesIO 版を用意（GitHub Actions の保存しない運用に最適）
#
# 提供関数:
#   1) zip_files(file_list, zip_path, ...)
#        : 複数ファイル → ディスク上に ZIP を作成
#   2) zip_dir(dir_path, zip_path, ...)
#        : ディレクトリ配下 → ディスク上に ZIP を作成（再帰）
#   3) to_zip_bytes_from_dir(dir_path, ...)
#        : ディレクトリ配下 → メモリ上の ZIP (bytes) を返す（再帰）
#   4) to_zip_bytes(file_entries, ...)
#        : 任意の(arcname, bytes)列を ZIP バイトにまとめる汎用関数
#
# 使用例:
#   from module.utils.zip_utils import to_zip_bytes_from_dir
#   zip_bytes = to_zip_bytes_from_dir("./output")  # メモリ上に作成
#
#   from module.utils.zip_utils import zip_files
#   zip_files(["./a.png", "./b.png"], "./bundle.zip", flatten=True)
#
# ライセンス: MIT（必要に応じて変更可）
# =============================================================================

from __future__ import annotations

import os
import io
import fnmatch
import zipfile
from pathlib import Path
from typing import Iterable, List, Tuple, Optional


# -----------------------------------------------------------------------------
# 内部ユーティリティ
# -----------------------------------------------------------------------------
def _iter_files_under(
    root: Path,
    include_hidden: bool = False,
    patterns: Optional[Iterable[str]] = None,
) -> Iterable[Path]:
    """
    root 以下のすべてのファイルを再帰で列挙する。
    patterns が指定された場合はワイルドカードでフィルタする（OR 条件）。
    """
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if not include_hidden and any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if patterns:
            name = p.name
            if not any(fnmatch.fnmatch(name, pat) for pat in patterns):
                continue
        yield p


def _open_zipfile(path_or_buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel: int = 9):
    """
    zipfile.ZipFile のラッパ。compresslevel は Python 3.7+ で有効。
    """
    try:
        return zipfile.ZipFile(path_or_buf, mode=mode, compression=compression, compresslevel=compresslevel)
    except TypeError:
        # 古いランタイムの場合 compresslevel が未対応のことがある
        return zipfile.ZipFile(path_or_buf, mode=mode, compression=compression)


# -----------------------------------------------------------------------------
# パブリック API
# -----------------------------------------------------------------------------
def zip_files(
    file_list: Iterable[str],
    zip_path: str,
    *,
    flatten: bool = True,
    compression=zipfile.ZIP_DEFLATED,
    compresslevel: int = 9,
    strict: bool = True,
) -> str:
    """
    複数ファイルを 1 つの ZIP にまとめてディスクに保存する。

    Args:
        file_list: 圧縮するファイルのパス群
        zip_path: 出力 ZIP ファイル（.zip）
        flatten: True=ZIP 内でファイル名のみ（フラット格納） / False=相対パスを保持
        compression: zipfile の圧縮方式
        compresslevel: 圧縮レベル（0-9）
        strict: True=存在しないファイルで例外、False=警告スキップ

    Returns:
        作成された ZIP のパス
    """
    file_list = list(file_list)
    if not file_list:
        raise ValueError("zip_files: file_list が空です。")

    os.makedirs(os.path.dirname(os.path.abspath(zip_path) or "."), exist_ok=True)

    with _open_zipfile(zip_path, mode="w", compression=compression, compresslevel=compresslevel) as zf:
        for fp in file_list:
            p = Path(fp)
            if not p.exists():
                if strict:
                    raise FileNotFoundError(f"zip_files: ファイルが見つかりません: {fp}")
                else:
                    print(f"[WARN] zip_files: スキップ（存在しない）: {fp}")
                    continue
            arcname = p.name if flatten else p.as_posix()
            zf.write(p.as_posix(), arcname=arcname)
    return zip_path


def zip_dir(
    dir_path: str,
    zip_path: str,
    *,
    base_in_zip: Optional[str] = None,
    include_hidden: bool = False,
    patterns: Optional[Iterable[str]] = None,
    compression=zipfile.ZIP_DEFLATED,
    compresslevel: int = 9,
) -> str:
    """
    ディレクトリ配下を再帰で ZIP にまとめ、ディスクに保存する。

    Args:
        dir_path: 対象ディレクトリ
        zip_path: 出力 ZIP ファイル
        base_in_zip: ZIP 内でルートにする仮想ディレクトリ名（None=直下）
        include_hidden: ドット始まりのファイル/フォルダも含めるか
        patterns: 例 ["*.png", "*.jpg"] のように指定でフィルタ
        compression, compresslevel: 圧縮指定

    Returns:
        作成された ZIP のパス
    """
    root = Path(dir_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"zip_dir: ディレクトリが見つかりません: {dir_path}")

    os.makedirs(os.path.dirname(os.path.abspath(zip_path) or "."), exist_ok=True)

    with _open_zipfile(zip_path, mode="w", compression=compression, compresslevel=compresslevel) as zf:
        for p in _iter_files_under(root, include_hidden=include_hidden, patterns=patterns):
            rel = p.relative_to(root).as_posix()
            arcname = f"{base_in_zip.strip('/')}/{rel}" if base_in_zip else rel
            zf.write(p.as_posix(), arcname=arcname)
    return zip_path


def to_zip_bytes_from_dir(
    dir_path: str,
    *,
    base_in_zip: Optional[str] = None,
    include_hidden: bool = False,
    patterns: Optional[Iterable[str]] = None,
    compression=zipfile.ZIP_DEFLATED,
    compresslevel: int = 9,
) -> bytes:
    """
    ディレクトリ配下を再帰で ZIP にまとめ、**bytes** として返す（ディスク不使用）。

    Args:
        dir_path: 対象ディレクトリ
        base_in_zip: ZIP 内でルートにする仮想ディレクトリ名（None=直下）
        include_hidden: ドット始まりを含めるか
        patterns: 例 ["*.png", "*.jpg"] のように指定でフィルタ
        compression, compresslevel: 圧縮指定

    Returns:
        ZIP バイト列
    """
    root = Path(dir_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"to_zip_bytes_from_dir: ディレクトリが見つかりません: {dir_path}")

    buf = io.BytesIO()
    with _open_zipfile(buf, mode="w", compression=compression, compresslevel=compresslevel) as zf:
        for p in _iter_files_under(root, include_hidden=include_hidden, patterns=patterns):
            rel = p.relative_to(root).as_posix()
            arcname = f"{base_in_zip.strip('/')}/{rel}" if base_in_zip else rel
            zf.write(p.as_posix(), arcname=arcname)
    return buf.getvalue()


def to_zip_bytes(
    entries: Iterable[Tuple[str, bytes]],
    *,
    compression=zipfile.ZIP_DEFLATED,
    compresslevel: int = 9,
) -> bytes:
    """
    任意の (arcname, data_bytes) の列を ZIP バイトにまとめて返す。

    Args:
        entries: (ZIP 内ファイル名, バイト列) の反復
        compression, compresslevel: 圧縮指定

    Returns:
        ZIP バイト列
    """
    buf = io.BytesIO()
    with _open_zipfile(buf, mode="w", compression=compression, compresslevel=compresslevel) as zf:
        for arcname, data in entries:
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("to_zip_bytes: data は bytes/bytearray を指定してください")
            zf.writestr(arcname, data)
    return buf.getvalue()
