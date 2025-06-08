
import xarray as xr
import subprocess
import urllib.request
import xarray as xr
import xarray as xr
import os


# ========================================
# gpvutils.py - MSM / GSM 両対応ユーティリティ
# ========================================
# モデル種別に応じて気象変数を抽出・リネームする関数を提供します。
# model 引数に "MSM" または "GSM" を指定してください。
# ========================================


# ----------------------------------------
# 変数抽出＆リネーム関数（共通インターフェース）
# ----------------------------------------
def extract_and_rename_variables(ds: xr.Dataset, variables: list, model: str = "MSM"):
    """
    指定モデルの GPV データから必要な変数を抽出・リネームするユーティリティ。

    Parameters
    ----------
    ds : xr.Dataset
        入力となるxarrayデータセット（NetCDF形式）
    variables : list of str
        取得したい変数名（例：['T850', 'Q700']）
    model : str
        'MSM' または 'GSM' を指定（デフォルト：'MSM'）

    Returns
    -------
    dict[str, xr.DataArray]
        変数名をキーとした辞書
    """

    # ------------------------------
    # MSM用マッピング
    # ------------------------------
    msm_mapping = {
        'T850': ('t', 850),
        'Q700': ('q', 700),
        'U850': ('u', 850),
        'V850': ('v', 850),
        'W700': ('w', 700),
        'MSLP': ('mslp', None),
    }

    # ------------------------------
    # GSM用マッピング
    # ------------------------------
    gsm_mapping = {
        'T850': ('TMP_850mb', None),
        'Q700': ('RH_700mb', None),
        'U850': ('UGRD_850mb', None),
        'V850': ('VGRD_850mb', None),
        'W700': ('VVEL_700mb', None),
        'MSLP': ('PRMSL_meansealevel', None),
    }

    # 使用マッピングを選択
    if model.upper() == "MSM":
        mapping = msm_mapping
    elif model.upper() == "GSM":
        mapping = gsm_mapping
    else:
        raise ValueError(f"対応していないモデル指定です: {model}")

    # 抽出処理
    output = {}
    for new_name in variables:
        if new_name not in mapping:
            continue
        orig_var, level = mapping[new_name]
        if orig_var not in ds:
            continue
        if level is not None:
            if "pressure" in ds[orig_var].dims:
                da = ds[orig_var].sel(pressure=level)
            else:
                continue
        else:
            da = ds[orig_var]
        output[new_name] = da.rename(new_name)

    return output

# ----------------------------------------
# サブプロセスを実行する関数（例：wgrib2コマンドなど外部コマンド用）
# ----------------------------------------
def run_subprocess(cmd: list):
    """
    指定されたコマンドをサブプロセスとして実行し、標準出力とエラーを取得して表示。
    エラーがあれば例外を発生させる。
    """
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(result.stdout)  # 実行結果の表示
        return result
    except subprocess.CalledProcessError as e:
        print("エラーが発生しました:", e.stderr)
        raise


# ----------------------------------------
# GRIB2ファイルをダウンロードする関数
# ----------------------------------------
def download_grib2bin(url: str, out_path: str):
    """
    指定されたURLからGRIB2ファイルをダウンロードして、指定したパスに保存。
    """
    urllib.request.urlretrieve(url, out_path)
    print(f"ダウンロード完了: {out_path}")


# ----------------------------------------
# GRIB2ファイルをNetCDFに変換する関数（wgrib2を使用）
# ----------------------------------------
def grib2bin_to_nc(grib2_path: str, nc_path: str):
    """
    GRIB2ファイルをNetCDF形式に変換する（wgrib2コマンドを利用）。
    """
    cmd = ["wgrib2", grib2_path, "-netcdf", nc_path]
    run_subprocess(cmd)


# ----------------------------------------
# NetCDFファイルをxarrayで読み込む関数
# ----------------------------------------
def load_dataset(nc_file: str):
    """
    NetCDFファイルをxarrayのDatasetとして読み込む。
    """
    ds = xr.open_dataset(nc_file)
    print(f"読み込み成功: {nc_file}")
    return ds

# ----------------------------------------
# MSMとGSMの切り替えに対応するダウンロード関数
# ----------------------------------------
def download_data(model: str, yyyymmddhh: str, out_dir: str = "./"):
    """
    モデル名（MSMまたはGSM）に応じて対応するデータをダウンロード。

    Parameters:
    ----------
    model : str
        "MSM" または "GSM"
    yyyymmddhh : str
        ダウンロード対象の時刻（例："2024070100"）
    out_dir : str
        保存先ディレクトリ

    Returns:
    -------
    str : ダウンロードしたファイルのパス
    """
    if model == "MSM":
        return download_msm_data(yyyymmddhh, out_dir)
    elif model == "GSM":
        return download_gsm_data(yyyymmddhh, out_dir)  # ※download_gsm_dataが定義されている場合
    else:
        raise ValueError("Unknown model: choose 'MSM' or 'GSM'")

import xarray as xr

# ----------------------------------------
# NetCDFファイルの変数リストを出力する関数
# ----------------------------------------
def list_variables(nc_path: str):
    """
    NetCDFファイル内の変数名を一覧表示する。

    Parameters
    ----------
    nc_path : str
        NetCDFファイルのパス
    """
    ds = xr.open_dataset(nc_path)
    print("変数一覧:")
    for var in ds.data_vars:
        print(f" - {var}")
    ds.close()


# ----------------------------------------
# GSM特有のパラメータを抽出して辞書化する関数
# ----------------------------------------
def extract_gsm_parameters(nc_path: str):
    """
    GSMデータから気温、風、湿度など代表的なパラメータを抽出。

    Parameters
    ----------
    nc_path : str
        NetCDFファイルのパス

    Returns
    -------
    dict[str, xarray.DataArray]
        変数名ごとのDataArray辞書
    """
    ds = xr.open_dataset(nc_path)
    params = {}
    for key in ["TMP", "UGRD", "VGRD", "RH", "PRMSL"]:
        if key in ds:
            params[key] = ds[key]
    return params


# ----------------------------------------
# 時刻のリストを渡して一括ダウンロード＆変換する関数
# ----------------------------------------
def batch_download_and_convert(model: str, times: list, out_dir: str = "./"):
    """
    MSMまたはGSMの複数時刻を一括でGRIB2取得→NetCDF変換。

    Parameters
    ----------
    model : str
        "MSM" または "GSM"
    times : list[str]
        対象時刻のリスト（例: ["2024051400", "2024051406"]）
    out_dir : str
        保存ディレクトリ
    """
    os.makedirs(out_dir, exist_ok=True)
    for t in times:
        print(f"処理中: {t}")
        grib_path = download_data(model, t, out_dir)
        nc_path = os.path.join(out_dir, f"{t}_{model}.nc")
        grib2bin_to_nc(grib_path, nc_path)

import matplotlib.pyplot as plt
import pandas as pd
import imageio
from pathlib import Path

# ----------------------------------------
# 指定変数を時系列で一括プロットして保存
# ----------------------------------------
def plot_variable_timeseries(param_dict, var_name, out_dir="./plots"):
    """
    同じ変数（例: TMP）の複数時刻をまとめてプロットして保存。

    Parameters
    ----------
    param_dict : dict[str, xarray.DataArray]
        各時刻の変数を格納した辞書（時刻文字列をキーにする）
    var_name : str
        表示対象の変数名
    out_dir : str
        出力ディレクトリ
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for time_str, data_array in param_dict.items():
        plt.figure()
        data_array.plot()
        plt.title(f"{var_name} at {time_str}")
        plt.savefig(f"{out_dir}/{var_name}_{time_str}.png")
        plt.close()


# ----------------------------------------
# PNG画像をGIFアニメに変換する
# ----------------------------------------
def create_gif_from_images(image_dir, pattern, gif_path, duration=0.5):
    """
    指定ディレクトリの画像を結合してGIFに変換。

    Parameters
    ----------
    image_dir : str
        PNG画像が保存されたディレクトリ
    pattern : str
        結合対象ファイル名のパターン（例: "TMP_*.png"）
    gif_path : str
        保存するGIFのパス
    duration : float
        各フレームの表示秒数（秒）
    """
    import glob
    image_files = sorted(glob.glob(f"{image_dir}/{pattern}"))
    images = [imageio.v2.imread(img) for img in image_files]
    imageio.mimsave(gif_path, images, duration=duration)
    print(f"GIF保存完了: {gif_path}")


# ----------------------------------------
# xarray変数をCSV/Excelとして保存
# ----------------------------------------
def save_variable_to_csv(data_array, out_csv, out_excel=None):
    """
    DataArray を DataFrame に変換し、CSV/Excel に出力。

    Parameters
    ----------
    data_array : xarray.DataArray
        保存対象の変数
    out_csv : str
        CSV出力パス
    out_excel : str or None
        Excel出力パス（必要であれば）
    """
    df = data_array.to_dataframe().reset_index()
    df.to_csv(out_csv, index=False)
    print(f"CSV保存完了: {out_csv}")
    if out_excel:
        df.to_excel(out_excel, index=False)
        print(f"Excel保存完了: {out_excel}")


# ----------------------------------------
# 複数変数を1枚の学習用データセットに統合
# ----------------------------------------
def create_training_dataset(param_dict, variables, out_path="dataset.csv"):
    """
    DataArrayの辞書から指定変数を1つの表にまとめてCSV保存。

    Parameters
    ----------
    param_dict : dict[str, xarray.Dataset]
        各時刻のNetCDFから抽出したデータセット（辞書）
    variables : list[str]
        抽出したい変数名（例: ["TMP", "RH"]）
    out_path : str
        CSV保存パス
    """
    records = []
    for time_str, ds in param_dict.items():
        for var in variables:
            if var in ds:
                df = ds[var].to_dataframe().reset_index()
                df["time"] = time_str
                df["var"] = var
                records.append(df)
    full_df = pd.concat(records, ignore_index=True)
    full_df.to_csv(out_path, index=False)
    print(f"学習用データセットを保存しました: {out_path}")

from matplotlib.backends.backend_pdf import PdfPages

# ----------------------------------------
# DataArrayをPDFとして保存する
# ----------------------------------------
def save_variable_to_pdf(data_array, out_pdf, title=None):
    """
    xarray.DataArray を画像化し、PDFに保存。

    Parameters
    ----------
    data_array : xarray.DataArray
        可視化対象の変数
    out_pdf : str
        出力PDFパス
    title : str or None
        グラフのタイトル（任意）
    """
    with PdfPages(out_pdf) as pdf:
        plt.figure()
        data_array.plot()
        if title:
            plt.title(title)
        pdf.savefig()
        plt.close()
    print(f"PDF保存完了: {out_pdf}")
