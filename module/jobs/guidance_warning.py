#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋田県の降水ガイダンス（数値予報＝予測値）を監視し、しきい値を超える予想が出た
ときだけ Discord にテキストで「予測アラート」を通知する。weather_warning.py と
同じ「取得→差分→変化時だけ通知」方式。標準ライブラリのみ。

★重要: これは気象庁の正式な「警報・注意報」ではない。数値予報ガイダンス（予測値）に
  対する自前のしきい値判定であり、通知は「○mm以上の予想」という予測情報。

データ源（Basic認証あり。bosai/advisor 全体が認証付き）:
  https://www.jma.go.jp/bosai/advisor/data/guid_table/
    time_{model}_rain.json             … 最新初期時刻  {"time": "...+00:00"}
    {YYYYMMDDHHMMSS}_{model}_rain.json  … 本体（rain1/rain3/rain24 × filterN × 区域コード）
    guid_area_class10.json             … 区域コード→名称
  認証は JMA_ADV_USER / JMA_ADV_PASS（guidance.py と同じ secret を流用）。

本体JSONの形:
  { "rain1": { "filter0": { "050010": [mm, mm, ...], ... }, "filter1": {...} },
    "rain3": {...}, "rain24": {...} }
  rain1/rain3 は27コマ（3時間刻み）、rain24 は20コマ。
"""
import base64
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

# ----------------------------- 設定 -----------------------------
BASE_URL = os.environ.get(
    "GUID_BASE_URL", "https://www.jma.go.jp/bosai/advisor/data/guid_table"
).rstrip("/")
MODEL = os.environ.get("GUID_MODEL", "gsm")        # gsm / msm
FILTER = os.environ.get("GUID_FILTER", "filter0")  # FLV（確率レベル）。filter0=上振れ側
AREA_PREFIX = os.environ.get("AREA_PREFIX", "05")  # 秋田県（05*）。class10コードの先頭一致
STATE_FILE = os.environ.get("STATE_FILE", "guidance_warning_state.json")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_GUIDANCE_WEBHOOK_URL", "")
JMA_USER = os.environ.get("JMA_ADV_USER", "").strip()
JMA_PASS = os.environ.get("JMA_ADV_PASS", "").strip()

# 監視要素としきい値(mm)。この値「以上」の予想で通知。env で上書き可。
THRESHOLDS = {
    "rain1": int(os.environ.get("GUID_RAIN1_MM", "20")),
    "rain3": int(os.environ.get("GUID_RAIN3_MM", "30")),
    "rain24": int(os.environ.get("GUID_RAIN24_MM", "50")),
}
ELEMENTS = [e.strip() for e in os.environ.get(
    "GUID_ELEMENTS", "rain1,rain3,rain24").split(",") if e.strip()]

# --- 風ガイダンス（別データセット。アメダス地点単位・m/s・filter階層なし）---
WIND_ENABLE = os.environ.get("GUID_WIND_ENABLE", "1").lower() in ("1", "true", "yes", "on")
WIND_BASE_URL = os.environ.get(
    "GUID_WIND_BASE_URL", "https://www.jma.go.jp/bosai/advisor/data/guid_table_wind"
).rstrip("/")
WIND_AREA_PREFIX = os.environ.get("WIND_AREA_PREFIX", "32")  # 秋田のアメダス地点コード先頭
WIND_MS = float(os.environ.get("GUID_WIND_MS", "15"))        # 最大風速(m/s)しきい値
# 地点名は公開のアメダス地点表（認証不要）で解決。
AMEDAS_TABLE_URL = os.environ.get(
    "AMEDAS_TABLE_URL", "https://www.jma.go.jp/bosai/amedas/const/amedastable.json")

# --- 寒気ガイダンス（cold_table。公開＝認証不要。22地点中インデックス6が秋田）---
COLD_ENABLE = os.environ.get("GUID_COLD_ENABLE", "1").lower() in ("1", "true", "yes", "on")
COLD_BASE_URL = os.environ.get(
    "GUID_COLD_BASE_URL", "https://www.jma.go.jp/bosai/advisor/data/cold_table"
).rstrip("/")
COLD_AREA_INDEX = os.environ.get("COLD_AREA_INDEX", "6")    # data["6"] = 秋田
COLD_AREA_NAME = os.environ.get("COLD_AREA_NAME", "秋田")
COLD_LEVELS = [s.strip() for s in os.environ.get(
    "COLD_LEVELS", "300,500,700,850,925").split(",") if s.strip()]
# 各面の「これ以下で通知」しきい値(℃)。気温=絶対値。寒気＝低温側。
# 既定は 500/850 のみ。300/700/925 は env(GUID_COLD_300 等)で設定するまで表示専用。
COLD_THRESHOLDS = {}
for _lv, _def in [("300", None), ("500", "-36"), ("700", None), ("850", "-6"), ("925", None)]:
    _v = os.environ.get(f"GUID_COLD_{_lv}", _def)
    COLD_THRESHOLDS[_lv] = float(_v) if _v not in (None, "") else None

# 平年差（℃）。これ以下（より低温側）で通知。平年値 tave.json は別系統:
# 気圧面→WMO地点番号→平年値(K)の配列（366日×2=732, 12時間ごと）。秋田=47582。
COLD_WMO = os.environ.get("COLD_WMO", "47582")  # 秋田の高層WMO番号
TAVE_URL = os.environ.get(
    "TAVE_URL", "https://www.jma.go.jp/bosai/advisor/const/tave.json")
COLD_DEV_THRESHOLDS = {}
for _lv, _def in [("300", None), ("500", "-6"), ("700", None), ("850", "-6"), ("925", None)]:
    _v = os.environ.get(f"GUID_COLDDEV_{_lv}", _def)
    COLD_DEV_THRESHOLDS[_lv] = float(_v) if _v not in (None, "") else None

ELEM_LABEL = {"rain1": "降水1時間", "rain3": "降水3時間", "rain24": "降水24時間", "wind": "風"}
ELEM_LABEL.update({f"cold{lv}": f"{lv}hPa気温" for lv in ("300", "500", "700", "850", "925")})
ELEM_LABEL.update({f"colddev{lv}": f"{lv}hPa平年差" for lv in ("300", "500", "700", "850", "925")})
ADVISOR_PORTAL = "https://www.jma.go.jp/bosai/advisor/"
JST = timezone(timedelta(hours=9))


# ----------------------------- 取得 -----------------------------
def _headers():
    h = {"User-Agent": "akita-guidance-warning/1.0"}
    if JMA_USER and JMA_PASS:
        token = base64.b64encode(f"{JMA_USER}:{JMA_PASS}".encode()).decode()
        h["Authorization"] = f"Basic {token}"
    return h


def fetch_json(url):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def latest_data_url():
    """time_{model}_rain.json から最新初期時刻を読み、本体JSONのURLとISO時刻を返す。"""
    idx = fetch_json(f"{BASE_URL}/time_{MODEL}_rain.json")
    iso = idx["time"]
    ts = _ts(iso)  # 2026-06-12T00:00:00+00:00 -> 20260612000000
    return f"{BASE_URL}/{ts}_{MODEL}_rain.json", iso


def area_name_map():
    """guid_area_class10.json から code->名称。構造不明でも壊れないよう寛容に解釈。"""
    try:
        raw = fetch_json(f"{BASE_URL}/guid_area_class10.json")
    except Exception as e:
        print(f"[WARN] area json 取得失敗（コード表示にフォールバック）: {e}", file=sys.stderr)
        return {}
    m = {}
    if isinstance(raw, dict):
        for code, v in raw.items():
            if isinstance(v, dict):
                m[code] = v.get("name") or v.get("kjName") or v.get("knName") or code
            elif isinstance(v, str):
                m[code] = v
    return m


def _parse_iso(iso):
    # rain は "+00:00"、wind は末尾 "Z" 形式。両対応にする。
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _ts(iso):
    # 本体JSONのファイル名は初期時刻(UTC)の YYYYMMDDHHMMSS（14桁）。
    # re.sub(\D) だと "+00:00" の桁まで拾うので、UTC正規化して整形する。
    return _parse_iso(iso).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def time_labels(init_iso, n):
    """予想各コマの JST ラベルを返す（rain1/rain3 用）。
    仮定: 初コマ = 初期時刻(JST) + 6h、以後3時間刻み。run依存のため“目安”。
    """
    init = _parse_iso(init_iso).astimezone(JST)
    t0 = init + timedelta(hours=6)
    return [t0 + timedelta(hours=3 * i) for i in range(n)]


def fmt_jst(dt):
    return f"{dt.month}/{dt.day} {dt.hour:02d}時"


def amedas_name_map():
    """公開のアメダス地点表（認証不要）から code->漢字名。失敗時はコード表示。"""
    try:
        raw = fetch_json(AMEDAS_TABLE_URL)
    except Exception as e:
        print(f"[WARN] amedas表 取得失敗（コード表示にフォールバック）: {e}", file=sys.stderr)
        return {}
    m = {}
    if isinstance(raw, dict):
        for code, v in raw.items():
            if isinstance(v, dict):
                m[code] = v.get("kjName") or v.get("knName") or code
    return m


# --------------------------- 抽出・判定 ---------------------------
# 各 scan は (exceed, lines, ref) を返す共通形式:
#   exceed: {地点名: set(要素キー)}            … 差分判定用
#   lines:  {(地点名, 要素キー): 表示行}        … しきい値超えの表示文
#   ref:    [(ソート値, 参考表示行), ...]        … 予想ピーク参考（しきい値未満も含む）
def scan_rain(data, init_iso):
    name_map = area_name_map()
    exceed, lines, ref = {}, {}, []
    for elem in ELEMENTS:
        block = data.get(elem, {}).get(FILTER, {})
        th = THRESHOLDS.get(elem)
        if th is None:
            continue
        labels = time_labels(init_iso, 27) if elem in ("rain1", "rain3") else None
        for code, values in block.items():
            if not code.startswith(AREA_PREFIX) or not values:
                continue
            name = name_map.get(code, code)
            peak = max(values)
            label_e = ELEM_LABEL.get(elem, elem)
            ref.append((peak, f"・{name} {label_e}：最大 {peak}mm"))
            if peak >= th:
                idx = values.index(peak)
                lab = fmt_jst(labels[idx]) if labels and idx < len(labels) else None
                when = f"（{lab}頃）" if lab else ""
                exceed.setdefault(name, set()).add(elem)
                lines[(name, elem)] = (
                    f"{name} {label_e}：最大 {peak}mm{when}予想 ※しきい値 {th}mm")
    return exceed, lines, ref


def scan_wind(data):
    name_map = amedas_name_map()
    exceed, lines, ref = {}, {}, []
    for area in data.get("areas", []):
        code = area.get("stationCode", "")
        speeds_raw = area.get("windSpeeds", [])
        if not code.startswith(WIND_AREA_PREFIX) or not speeds_raw:
            continue
        try:
            speeds = [float(x) for x in speeds_raw]
        except (TypeError, ValueError):
            continue
        if not speeds:
            continue
        peak = max(speeds)
        idx = speeds.index(peak)
        dirs = area.get("windDirections", [])
        wdir = dirs[idx] if idx < len(dirs) else ""
        name = name_map.get(code, code)
        ref.append((peak, f"・{name} 風：最大 {peak:.1f}m/s"))
        if peak >= WIND_MS:
            exceed.setdefault(name, set()).add("wind")
            wd = f"（{wdir}）" if wdir else ""
            lines[(name, "wind")] = (
                f"{name} 風：最大風速 {peak:.1f}m/s{wd} 予想 ※しきい値 {WIND_MS:.0f}m/s")
    return exceed, lines, ref


def cold_series():
    """寒気ガイダンスを全FTファイル連結して、秋田(COLD_AREA_INDEX)の
    {気圧面: [(JST時刻, 気温℃), ...]} を返す。時刻は ref_time + fts で確定。"""
    init_iso = fetch_json(f"{COLD_BASE_URL}/time_{MODEL}.json")["time"]
    init = _parse_iso(init_iso).astimezone(JST)
    ts = _ts(init_iso)
    series = {lv: [] for lv in COLD_LEVELS}
    start = 0
    for _ in range(12):  # 安全上限。FTファイルを順にたどる
        try:
            j = fetch_json(f"{COLD_BASE_URL}/{MODEL}_{ts}_{start}.json")
        except Exception:
            break
        fts = j.get("fts", [])
        area = j.get("data", {}).get(COLD_AREA_INDEX, {})
        for lv in COLD_LEVELS:
            vals = area.get(lv, [])
            for i, ft in enumerate(fts):
                if i < len(vals):
                    series[lv].append((init + timedelta(hours=ft), vals[i]))
        if not fts:
            break
        start = fts[-1] + 6
    return series, init_iso


def _tave_index(dt):
    """平年値配列(366日×2=732)のインデックス。UTCの暦日(閏暦)＋前半/後半で引く。"""
    u = dt.astimezone(timezone.utc)
    doy0 = (date(2000, u.month, u.day) - date(2000, 1, 1)).days  # 0始まり・閏暦
    return doy0 * 2 + (0 if u.hour < 12 else 1)


def scan_cold(series):
    exceed, lines, ref = {}, {}, []
    name = COLD_AREA_NAME
    tave = None
    try:
        tave = fetch_json(TAVE_URL)
    except Exception as e:
        print(f"[WARN] 平年値(tave)取得失敗、平年差スキップ: {e}", file=sys.stderr)
    for order, lv in enumerate(COLD_LEVELS):
        pts = series.get(lv, [])
        if not pts:
            continue
        parts = []
        # 気温（絶対値）。期間内の最低＝最も強い寒気。
        dt_min, vmin = min(pts, key=lambda p: p[1])
        parts.append(f"気温 最低 {vmin:.1f}℃")
        tthr = COLD_THRESHOLDS.get(lv)
        if tthr is not None and vmin <= tthr:
            e = f"cold{lv}"
            exceed.setdefault(name, set()).add(e)
            lines[(name, e)] = (f"{name} {lv}hPa気温：最低 {vmin:.1f}℃"
                                f"（{fmt_jst(dt_min)}頃）予想 ※しきい値 {tthr:.0f}℃以下")
        # 平年差 = 予報℃ − (平年K − 273.15)。期間内で最も平年を下回るコマ。
        clim = (tave or {}).get(lv, {}).get(COLD_WMO)
        if clim:
            devs = [(dt, val - (clim[_tave_index(dt)] - 273.15))
                    for dt, val in pts if _tave_index(dt) < len(clim)]
            if devs:
                dt_d, dmin = min(devs, key=lambda p: p[1])
                parts.append(f"平年差 {dmin:+.1f}℃")
                dthr = COLD_DEV_THRESHOLDS.get(lv)
                if dthr is not None and dmin <= dthr:
                    e = f"colddev{lv}"
                    exceed.setdefault(name, set()).add(e)
                    lines[(name, e)] = (f"{name} {lv}hPa平年差：最低 {dmin:+.1f}℃"
                                        f"（{fmt_jst(dt_d)}頃）予想 ※しきい値 {dthr:+.0f}℃以下")
        ref.append((order, f"・{name} {lv}hPa：" + " ／ ".join(parts)))
    return exceed, lines, ref


# --------------------------- 状態管理 ---------------------------
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return {k: set(v) for k, v in json.load(f).items()}
    except Exception:
        return {}


def save_state(state):
    d = os.path.dirname(STATE_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({k: sorted(v) for k, v in state.items()},
                  f, ensure_ascii=False, indent=2, sort_keys=True)


def diff_states(prev, curr):
    added, cleared = [], []
    for area in set(prev) | set(curr):
        p, c = prev.get(area, set()), curr.get(area, set())
        added += [(area, e) for e in c - p]
        cleared += [(area, e) for e in p - c]
    return added, cleared


# ----------------------------- Discord -----------------------------
def send_discord(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=data,
        headers={
            "Content-Type": "application/json",
            # UA を付けないと Cloudflare に 403 で弾かれる
            "User-Agent": "akita-guidance-warning/1.0 (+https://github.com/)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status


def wind_latest_data_url():
    idx = fetch_json(f"{WIND_BASE_URL}/time_{MODEL}_wind.json")
    iso = idx["time"]
    ts = _ts(iso)
    return f"{WIND_BASE_URL}/{ts}_{MODEL}_wind.json", iso


# ----------------------------- main -----------------------------
def main():
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_GUIDANCE_WEBHOOK_URL が未設定です", file=sys.stderr)
        sys.exit(1)
    if not (JMA_USER and JMA_PASS):
        print("JMA_ADV_USER / JMA_ADV_PASS が未設定です", file=sys.stderr)
        sys.exit(1)

    # 降水（GSM/MSM走行直後のみファイルが存在する。未公開時は 404 → 正常終了）
    try:
        data_url, init_iso = latest_data_url()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"降水ガイダンス未公開（404）— 次回実行まで待機: {e.url}")
            sys.exit(0)
        raise
    exceed, lines, ref = scan_rain(fetch_json(data_url), init_iso)

    # 風（取得失敗してもスキップして降水だけ通知する）
    if WIND_ENABLE:
        try:
            wurl, _ = wind_latest_data_url()
            we, wl, wr = scan_wind(fetch_json(wurl))
            for a, s in we.items():
                exceed.setdefault(a, set()).update(s)
            lines.update(wl)
            wr.sort(reverse=True)
            ref += wr[:8]  # 風は地点数が多いので上位8地点だけ参考表示
        except Exception as e:
            print(f"[WARN] 風ガイダンス取得失敗（スキップ）: {e}", file=sys.stderr)

    # 寒気（公開データ。秋田=index6・全気圧面の気温）
    if COLD_ENABLE:
        try:
            cseries, _ = cold_series()
            ce, cl, cr = scan_cold(cseries)
            for a, s in ce.items():
                exceed.setdefault(a, set()).update(s)
            lines.update(cl)
            ref += cr
        except Exception as e:
            print(f"[WARN] 寒気ガイダンス取得失敗（スキップ）: {e}", file=sys.stderr)

    prev = load_state()
    added, cleared = diff_states(prev, exceed)

    if not added and not cleared:
        print("変化なし")
        save_state(exceed)
        return

    def disp(a, e):
        return lines.get((a, e), f"{a} {ELEM_LABEL.get(e, e)}")

    blocks = []
    if added:
        blocks.append("**🆕 しきい値到達（予想）**\n" + "\n".join(
            disp(a, e) for a, e in sorted(added)))
    if cleared:
        blocks.append("**✅ しきい値を下回った（予想）**\n" + "\n".join(
            f"{a} {ELEM_LABEL.get(e, e)}：しきい値未満に" for a, e in sorted(cleared)))
    if exceed:
        now = ["・" + disp(a, e) for a in sorted(exceed) for e in sorted(exceed[a])]
        blocks.append("**現在しきい値超えの予想**\n" + "\n".join(now))
    if ref:
        blocks.append("**参考：予想ピーク**\n" + "\n".join(t for _, t in ref))

    blocks.append(f"**🔗 関連リンク**\n[気象庁 ガイダンス（要ログイン）]({ADVISOR_PORTAL})")

    footer = (f"数値予報ガイダンス {MODEL.upper()}（降水={FILTER} / 風=アメダス地点）"
              f"・予測値で気象庁の正式な警報ではありません／降水初期時刻 {init_iso}")

    payload = {
        "embeds": [{
            "title": "🌧️💨🥶 秋田県 ガイダンス予測アラート（降水・風・寒気）",
            "description": "\n\n".join(blocks)[:4000],
            "color": 0x1E88E5,  # 青（予測情報）
            "footer": {"text": footer[:2048]},
        }]
    }
    print("通知:", send_discord(payload))
    save_state(exceed)


if __name__ == "__main__":
    main()
