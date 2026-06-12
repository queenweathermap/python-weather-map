#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋田県の気象警報・注意報＋林野火災注意報・警報を監視し、変化時だけ Discord 通知する。

- 気象警報・注意報: 気象庁が自サイト向けに公開している JSON（非公式エンドポイント）。
- 林野火災注意報・警報: konno-system.wew.jp の「気象情報収集支援システム」の HTML 表
  （★気象庁の一次情報ではなく第三者の個人運営サイト。HTML 改修で壊れる前提。
    FOREST_FIRE_URL を空にすれば無効化できる）。
前回の発表状況を STATE_FILE に保存し、差分（新規発表 / 解除）が出たときだけ通知する。
"""
import json
import os
import re
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

# 林野火災注意報・警報用 気象情報収集支援システム（秋田県のHTML表）。
# ★気象庁の一次情報ではなく第三者（個人運営）サイト。HTML構造変更で壊れる前提。
# 空文字にすると林野火災の監視を無効化できる。
FOREST_FIRE_URL = os.environ.get(
    "FOREST_FIRE_URL",
    "https://konno-system.wew.jp/forest_fire_alert/get_information_today.php",
).strip()

# 通知に併記する関連リンク（embed 内に markdown リンクで入れる＝サムネは出ない）。
AKITA_BOSAI_URL = "https://www.bousai-akita.jp/"                       # 秋田県防災ポータル
FOREST_FIRE_PORTAL_URL = "https://konno-system.wew.jp/forest_fire_alert/portal.php"

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


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "akita-weather-alert/1.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


def resolve_fire(label):
    """林野火災ラベル -> (名称, 種別)。警報を含めば警報級、それ以外は注意報級。"""
    return (label, "警報" if "警報" in label else "注意報")


def parse_forest_fire(html_text):
    """支援システムのHTML表から、林野火災の注意報/警報が出ている地点だけを
    {"市町村・アメダス": set(["林野火災注意報"|"林野火災警報"])} で返す。
    「なし」の地点は含めない（＝発表中のものだけ state 差分の対象になる）。

    表は 消防本部名/市町村名 が rowspan でまとまっており、行のセル数で判別する:
      8列 = 消防本部・市町村・アメダス＋データ5列
      7列 = 市町村・アメダス＋データ5列（消防本部は上から継続）
      6列 = アメダス＋データ5列（消防本部・市町村とも上から継続）
    末尾5列は 前3日/前30日/乾燥/強風/林野火災 の順。前3日が数値の行だけをデータ行と見なす
    （ヘッダ・脚注・「アメダスなし」行を自動的に除外）。
    """
    clean = lambda s: re.sub(r"<[^>]+>", "", s).replace("　", " ").replace("\n", " ").strip()
    num = re.compile(r"^-?\d+(?:\.\d+)?$")
    result = {}
    cur_city = ""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        cells = [clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
        n = len(cells)
        if n not in (6, 7, 8):
            continue
        if not num.match(cells[n - 5]):   # 前3日間計が数値でなければデータ行ではない
            continue
        amedas = cells[n - 6]
        status = cells[n - 1]
        if n == 8:
            cur_city = cells[1]
        elif n == 7:
            cur_city = cells[0]
        # n == 6 は市町村が上の行から継続するので cur_city を維持
        if "警報" in status:
            label = "林野火災警報"
        elif "注意報" in status:
            label = "林野火災注意報"
        else:
            continue                       # 「なし」など
        key = f"{cur_city}・{amedas}" if cur_city else amedas
        result.setdefault(key, set()).add(label)
    return result


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
    """{"warnings": {区域名: set(コード)}, "fire": {地点: set(ラベル)}} を返す。"""
    empty = {"warnings": {}, "fire": {}}
    if not os.path.exists(STATE_FILE):
        return empty
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return empty
    if "warnings" in raw or "fire" in raw:
        return {
            "warnings": {k: set(v) for k, v in raw.get("warnings", {}).items()},
            "fire": {k: set(v) for k, v in raw.get("fire", {}).items()},
        }
    # 旧形式（{区域名: [コード]} のフラット）は気象警報として読み込む。
    return {"warnings": {k: set(v) for k, v in raw.items()}, "fire": {}}


def save_state(warnings, fire):
    # 保存先ディレクトリ（例: data/）が無ければ作る。これが無いと初回に
    # open() が FileNotFoundError になるため、2ファイルだけで完結させる保険。
    state_dir = os.path.dirname(STATE_FILE)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
    payload = {
        "warnings": {k: sorted(v) for k, v in warnings.items()},
        "fire": {k: sorted(v) for k, v in fire.items()},
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)


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
    curr_w = current_warnings(warning_json, name_map)

    state = load_state()
    prev_w, prev_f = state["warnings"], state["fire"]

    # 林野火災（第三者サイト）。取得・解析に失敗したら前回値を据え置き、
    # 誤った「解除」通知が出ないようにする。
    if FOREST_FIRE_URL:
        try:
            curr_f = parse_forest_fire(fetch_text(FOREST_FIRE_URL))
        except Exception as e:
            print(f"林野火災データ取得/解析に失敗（前回値を据え置き）: {e}", file=sys.stderr)
            curr_f = dict(prev_f)
    else:
        curr_f = dict(prev_f)

    added_w, cleared_w = diff_states(prev_w, curr_w)
    added_f, cleared_f = diff_states(prev_f, curr_f)

    if not (added_w or cleared_w or added_f or cleared_f):
        print("変化なし")
        save_state(curr_w, curr_f)
        return

    office = warning_json.get("publishingOffice", "気象庁")
    report_dt = warning_json.get("reportDatetime", "")

    # 色は「新規・追加」の最重大度（気象＋林野火災）で決める。
    added_kinds = [resolve(w)[1] for _, w in added_w] + \
                  [resolve_fire(l)[1] for _, l in added_f]
    color = 0x2196F3
    if added_kinds:
        top = max(added_kinds, key=lambda k: SEVERITY[k])
        color = KIND_COLOR[top]

    def code_key(c):
        return (0, int(c)) if c.isdigit() else (1, c)

    blocks = []
    add_lines = [f"{a}：{resolve(w)[0]}" for a, w in sorted(added_w)] + \
                [f"{a}：🔥{resolve_fire(l)[0]}" for a, l in sorted(added_f)]
    if add_lines:
        blocks.append("**🆕 新規・追加**\n" + "\n".join(add_lines))

    clr_lines = [f"{a}：{resolve(w)[0]}" for a, w in sorted(cleared_w)] + \
                [f"{a}：🔥{resolve_fire(l)[0]}" for a, l in sorted(cleared_f)]
    if clr_lines:
        blocks.append("**✅ 解除**\n" + "\n".join(clr_lines))

    if curr_w:
        now = []
        for a in sorted(curr_w):
            names = "、".join(resolve(w)[0] for w in sorted(curr_w[a], key=code_key))
            now.append(f"・{a}：{names}")
        blocks.append("**現在発表中（気象警報・注意報）**\n" + "\n".join(now))
    else:
        blocks.append("**現在発表中（気象警報・注意報）**\n発表中の警報・注意報はありません")

    if curr_f:
        now_f = ["・{}：{}".format(a, "、".join(sorted(curr_f[a]))) for a in sorted(curr_f)]
        blocks.append("**🔥 林野火災 注意報・警報（発表中）**\n" + "\n".join(now_f))

    # 関連リンク（カテゴリ別に、その種別のアラートがある時だけ併記。
    # embed 内の markdown リンクなのでサムネは出ず、リンクテキストだけ表示される）。
    links = []
    if added_w or cleared_w or curr_w:
        links.append(f"[秋田県防災ポータルサイト]({AKITA_BOSAI_URL})")
    if added_f or cleared_f or curr_f:
        links.append(f"[林野火災注意報・警報用 気象情報収集支援システム]({FOREST_FIRE_PORTAL_URL})")
    if links:
        blocks.append("**🔗 関連リンク**\n" + "\n".join(links))

    footer = f"{office}／発表 {report_dt}"
    if added_f or cleared_f or curr_f:
        footer += "　／林野火災データ: konno-system.wew.jp（非公式）"

    payload = {
        "embeds": [{
            "title": "⚠️ 秋田県 気象警報・注意報の更新",
            "description": "\n\n".join(blocks)[:4000],
            "color": color,
            "footer": {"text": footer[:2048]},
        }]
    }
    print("通知:", send_discord(payload))
    save_state(curr_w, curr_f)


if __name__ == "__main__":
    main()
