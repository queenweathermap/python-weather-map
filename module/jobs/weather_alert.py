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

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

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

KIND_COLOR = {
    "特別警報": 0x9C27B0,  # 紫
    "警報": 0xE53935,      # 赤
    "注意報": 0xFDD835,    # 黄
}
SEVERITY = {"特別警報": 3, "警報": 2, "注意報": 1}


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
    """{区域名: set(警報コード)} を返す（解除・該当なしは除外）。"""
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
            if w.get("status") != "解除" and w.get("code") in WARNING_INFOS
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
        headers={"Content-Type": "application/json"}, method="POST",
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
        print("DISCORD_WEBHOOK_URL が未設定です", file=sys.stderr)
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
        top = max((WARNING_INFOS[w][1] for _, w in added), key=lambda k: SEVERITY[k])
        color = KIND_COLOR[top]

    blocks = []
    if added:
        blocks.append("**🆕 新規・追加**\n" + "\n".join(
            f"{a}：{WARNING_INFOS[w][0]}" for a, w in sorted(added)))
    if cleared:
        blocks.append("**✅ 解除**\n" + "\n".join(
            f"{a}：{WARNING_INFOS[w][0]}" for a, w in sorted(cleared)))
    if curr:
        now = []
        for a in sorted(curr):
            names = "、".join(
                WARNING_INFOS[w][0] for w in sorted(curr[a], key=lambda x: int(x)))
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
