#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋田県の気象警報・注意報を監視し、変化があったときだけ Discord に通知する。

気象庁が自サイト向けに公開している警報・注意報 JSON を利用（非公式エンドポイント）。
前回の発表状況を state.json に保存し、差分（新規発表 / 解除）が出たときだけ通知する。
"""
import json
import os
import sys
import urllib.request

# ----------------------------- 設定 -----------------------------
AREA_CODE = "050000"  # 秋田県
WARNING_JSON_URL = f"https://www.jma.go.jp/bosai/warning/data/warning/{AREA_CODE}.json"
AREA_NAME_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
STATE_FILE = os.environ.get("STATE_FILE", "state.json")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WARNING_WEBHOOK_URL", "")

# 二次細分区域名の一部で絞り込み（例: "秋田中央"）。空なら秋田県全域を監視。
# どの区域名があるかは LIST_AREAS=1 で確認できる。
AREA_FILTER = os.environ.get("AREA_FILTER", "").strip()

# 警報・注意報コード → (名称, 種別)
WARNING_INFOS = {
    "33": ("大雨特別警報", "特別警報"),
    "32": ("暴風雪特別警報", "特別警報"),
    "36": ("大雪特別警報", "特別警報"),
    "35": ("暴風特別警報", "特別警報"),
    "37": ("波浪特別警報", "特別警報"),
    "38": ("高潮特別警報", "特別警報"),
    # 2026年5月29日からの新体系（危険警報＝警戒レベル4相当）。
    # 出典: 気象庁防災情報XML「警報等情報要素コード管理表」表1.5.3.1
    #   （jmaxml_20260430_code.xlsx, https://xml.kishou.go.jp/tec_material.html）。
    # サンプル電文 VPWW55/56 にも Code=43/49 が実在することを確認済み（推測値ではない）。
    "43": ("大雨危険警報", "危険警報"),
    "48": ("高潮危険警報", "危険警報"),
    "49": ("土砂災害危険警報", "危険警報"),
    "03": ("大雨警報", "警報"),
    "04": ("洪水警報", "警報"),
    "05": ("暴風警報", "警報"),
    "02": ("暴風雪警報", "警報"),
    "06": ("大雪警報", "警報"),
    "07": ("波浪警報", "警報"),
    "08": ("高潮警報", "警報"),
    "10": ("大雨注意報", "注意報"),
    "18": ("洪水注意報", "注意報"),
    "15": ("強風注意報", "注意報"),
    "13": ("風雪注意報", "注意報"),
    "12": ("大雪注意報", "注意報"),
    "16": ("波浪注意報", "注意報"),
    "19": ("高潮注意報", "注意報"),
    "14": ("雷注意報", "注意報"),
    "17": ("融雪注意報", "注意報"),
    "20": ("濃霧注意報", "注意報"),
    "21": ("乾燥注意報", "注意報"),
    "22": ("なだれ注意報", "注意報"),
    "23": ("低温注意報", "注意報"),
    "24": ("霜注意報", "注意報"),
    "25": ("着氷注意報", "注意報"),
    "26": ("着雪注意報", "注意報"),
}

# --- 危険警報（新体系）コードについての補足 -------------------------------
# 上の WARNING_INFOS に追記済み（43=大雨 / 48=高潮 / 49=土砂災害）。一次情報の
# 「警報等情報要素コード管理表」表1.5.3.1 と実サンプル電文(VPWW55/56)で確認した値。
# ・氾濫危険警報は WeatherWarning 要素に専用コードが存在しない（指定河川洪水予報
#   という別電文＝この warning JSON には出ない）。経過措置として当面は大雨危険警報
#   等として発表されるため、ここに氾濫用コードは追加しない（推測で足さない）。
# ・土砂災害(49)は土砂災害警戒情報という別系統でも発表される。本JSONに出ない可能性が
#   あるが、出た場合に正しい名称で表示できるよう登録してある（出なければ未使用なだけ）。
# ・未登録コードが届いても resolve() が「コードXX（未対応・要確認）」で通知するため
#   取りこぼしは起きない。
# --------------------------------------------------------------------------

KIND_COLOR = {
    "特別警報": 0x9C27B0,  # 紫
    "危険警報": 0xD81B60,  # 濃いピンク（レベル4相当）
    "警報": 0xE53935,      # 赤
    "注意報": 0xFDD835,    # 黄
    "不明": 0xFF6F00,      # オレンジ（未対応コード）
}
SEVERITY = {"特別警報": 4, "危険警報": 3, "不明": 3, "警報": 2, "注意報": 1}


def resolve(code):
    """コード -> (名称, 種別)。未知コードは要確認として返す。"""
    if code in WARNING_INFOS:
        return WARNING_INFOS[code]
    return (f"コード{code}（未対応・要確認）", "不明")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "akita-weather-alert/1.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def build_area_name_map():
    """area.json の全階層から code -> 名称 の辞書を作る。"""
    data = fetch_json(AREA_NAME_URL)
    name_map = {}
    for level in ("centers", "offices", "class10s", "class15s", "class20s"):
        for code, info in data.get(level, {}).items():
            name_map[code] = info.get("name", code)
    return name_map


def current_warnings(warning_json, name_map):
    """{区域名: set(警報コード)} を返す（解除・コード00は除外。未知コードは残す）。"""
    result = {}
    area_types = warning_json.get("areaTypes", [])
    if not area_types:
        return result
    for area in area_types[0].get("areas", []):
        name = name_map.get(area.get("code", ""), area.get("code", ""))
        if AREA_FILTER and AREA_FILTER not in name:
            continue
        active = {
            w.get("code", "")
            for w in area.get("warnings", [])
            if w.get("status") != "解除" and w.get("code") not in ("", "00")
        }
        if active:
            result[name] = active
    return result


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return {k: set(v) for k, v in json.load(f).items()}
    except Exception:
        return {}


def save_state(state):
    # 保存先ディレクトリ（例: data/）が無ければ作る。これが無いと初回に
    # open() が FileNotFoundError になるため、2ファイルだけで完結させる保険。
    state_dir = os.path.dirname(STATE_FILE)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {k: sorted(v) for k, v in state.items()},
            f, ensure_ascii=False, indent=2, sort_keys=True,
        )


def diff_states(prev, curr):
    added, cleared = [], []
    for area in set(prev) | set(curr):
        p, c = prev.get(area, set()), curr.get(area, set())
        added += [(area, w) for w in c - p]
        cleared += [(area, w) for w in p - c]
    return added, cleared


def send_discord(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL, data=data,
        headers={
            "Content-Type": "application/json",
            # UA を付けないと urllib 既定の "Python-urllib/x.y" が送られ、
            # Discord 前段の Cloudflare に 403 Forbidden で弾かれる。
            "User-Agent": "akita-weather-alert/1.0 (+https://github.com/)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status


def main():
    # 区域名の確認用。LIST_AREAS=1 で一覧を出して終了。
    if os.environ.get("LIST_AREAS") == "1":
        name_map = build_area_name_map()
        for area in fetch_json(WARNING_JSON_URL)["areaTypes"][0]["areas"]:
            print(area["code"], name_map.get(area["code"], "?"))
        return

    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WARNING_WEBHOOK_URL が未設定です", file=sys.stderr)
        sys.exit(1)

    warning_json = fetch_json(WARNING_JSON_URL)
    name_map = build_area_name_map()
    curr = current_warnings(warning_json, name_map)
    prev = load_state()
    added, cleared = diff_states(prev, curr)

    if not added and not cleared:
        print("変化なし")
        save_state(curr)
        return

    office = warning_json.get("publishingOffice", "気象庁")
    report_dt = warning_json.get("reportDatetime", "")

    color = 0x2196F3
    if added:
        top = max((resolve(w)[1] for _, w in added), key=lambda k: SEVERITY[k])
        color = KIND_COLOR[top]

    def code_key(c):
        return (0, int(c)) if c.isdigit() else (1, c)

    blocks = []
    if added:
        blocks.append("**🆕 新規・追加**\n" + "\n".join(
            f"{a}：{resolve(w)[0]}" for a, w in sorted(added)))
    if cleared:
        blocks.append("**✅ 解除**\n" + "\n".join(
            f"{a}：{resolve(w)[0]}" for a, w in sorted(cleared)))
    if curr:
        now = []
        for a in sorted(curr):
            names = "、".join(
                resolve(w)[0] for w in sorted(curr[a], key=code_key))
            now.append(f"・{a}：{names}")
        blocks.append("**現在発表中**\n" + "\n".join(now))
    else:
        blocks.append("**現在発表中**\n発表中の警報・注意報はありません")

    payload = {
        "embeds": [{
            "title": "⚠️ 秋田県 気象警報・注意報の更新",
            "description": "\n\n".join(blocks)[:4000],
            "color": color,
            "footer": {"text": f"{office}／発表 {report_dt}"},
        }]
    }
    print("通知:", send_discord(payload))
    save_state(curr)


if __name__ == "__main__":
    main()
