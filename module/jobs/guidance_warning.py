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
from datetime import datetime, timedelta, timezone

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

ELEM_LABEL = {"rain1": "降水1時間", "rain3": "降水3時間", "rain24": "降水24時間"}
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
    ts = re.sub(r"\D", "", iso)  # 2026-06-12T00:00:00+00:00 -> 20260612000000
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


def time_labels(init_iso, n):
    """予想各コマの JST ラベルを返す（rain1/rain3 用）。
    仮定: 初コマ = 初期時刻(JST) + 6h、以後3時間刻み。run依存のため“目安”。
    """
    init = datetime.fromisoformat(init_iso).astimezone(JST)
    t0 = init + timedelta(hours=6)
    return [t0 + timedelta(hours=3 * i) for i in range(n)]


def fmt_jst(dt):
    return f"{dt.month}/{dt.day} {dt.hour:02d}時"


# --------------------------- 抽出・判定 ---------------------------
def scan(data, init_iso):
    """しきい値超えの (区域名, 要素) を集める。
    返り値:
      exceed:  {区域名: set(要素キー)}        … 差分判定用
      detail:  {(区域名, 要素キー): (peak_mm, peak_label)} … 表示用
      peaks:   {(区域名, 要素キー): peak_mm}   … 参考表示（しきい値未満も含む）
    """
    name_map = area_name_map()
    exceed, detail, peaks = {}, {}, {}
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
            peaks[(name, elem)] = peak
            if peak >= th:
                idx = values.index(peak)
                label = fmt_jst(labels[idx]) if labels and idx < len(labels) else None
                exceed.setdefault(name, set()).add(elem)
                detail[(name, elem)] = (peak, label)
    return exceed, detail, peaks


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


def line_for(area, elem, detail):
    peak, label = detail.get((area, elem), (None, None))
    th = THRESHOLDS.get(elem)
    when = f"（{label}頃）" if label else ""
    return f"{area} {ELEM_LABEL.get(elem, elem)}：最大 {peak}mm{when}予想 ※しきい値 {th}mm"


# ----------------------------- main -----------------------------
def main():
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_GUIDANCE_WEBHOOK_URL が未設定です", file=sys.stderr)
        sys.exit(1)
    if not (JMA_USER and JMA_PASS):
        print("JMA_ADV_USER / JMA_ADV_PASS が未設定です", file=sys.stderr)
        sys.exit(1)

    data_url, init_iso = latest_data_url()
    data = fetch_json(data_url)

    exceed, detail, peaks = scan(data, init_iso)
    prev = load_state()
    added, cleared = diff_states(prev, exceed)

    if not added and not cleared:
        print("変化なし")
        save_state(exceed)
        return

    blocks = []
    if added:
        blocks.append("**🆕 しきい値到達（予想）**\n" + "\n".join(
            line_for(a, e, detail) for a, e in sorted(added)))
    if cleared:
        blocks.append("**✅ しきい値を下回った（予想）**\n" + "\n".join(
            f"{a} {ELEM_LABEL.get(e, e)}：しきい値未満に" for a, e in sorted(cleared)))

    if exceed:
        now = []
        for a in sorted(exceed):
            for e in sorted(exceed[a]):
                now.append("・" + line_for(a, e, detail))
        blocks.append("**現在しきい値超えの予想**\n" + "\n".join(now))

    # 参考: 秋田県内の各要素の予想ピーク（しきい値未満も含む）
    if peaks:
        ref = []
        for (a, e) in sorted(peaks):
            ref.append(f"・{a} {ELEM_LABEL.get(e, e)}：最大 {peaks[(a, e)]}mm")
        blocks.append("**参考：予想ピーク（全地点）**\n" + "\n".join(ref))

    blocks.append(f"**🔗 関連リンク**\n[気象庁 ガイダンス（要ログイン）]({ADVISOR_PORTAL})")

    footer = (f"数値予報ガイダンス {MODEL.upper()}/{FILTER}（予測値・気象庁の正式な警報ではありません）"
              f"／初期時刻 {init_iso}")

    payload = {
        "embeds": [{
            "title": "🌧️ 秋田県 降水ガイダンス 予測アラート",
            "description": "\n\n".join(blocks)[:4000],
            "color": 0x1E88E5,  # 青（予測情報）
            "footer": {"text": footer[:2048]},
        }]
    }
    print("通知:", send_discord(payload))
    save_state(exceed)


if __name__ == "__main__":
    main()
