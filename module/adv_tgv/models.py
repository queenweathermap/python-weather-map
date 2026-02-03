# -*- coding: utf-8 -*-
# =============================================================================
# module/adv_tgv/models.py
# ADV TGV のモデル/アイテム定義（増やすのはここだけ）
# =============================================================================

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Item:
    label: str
    base: str
    layer: str
    view_base: str
    view_digits: int
    jpg_prefix: str

    # 配信先ごとの既定（必要なら使う）
    email_default: bool = True
    slack_default: bool = True
    notion_default: bool = True


@dataclass(frozen=True)
class ModelCfg:
    referer: str
    init_step_hours: int
    rjtd_minute: int
    init_probe_item: Item
    ft_list: List[int]
    items: List[Item]


def ft_list_gsm() -> List[int]:
    return list(range(3, 73, 3))  # 3,6,9,...,72

def ft_list_msm() -> List[int]:
    return list(range(1, 73))  # 1..72

def ft_list_lfm() -> List[int]:
    return list(range(4, 19))  # 4..18



def load_model_groups() -> Dict[str, ModelCfg]:
    GSM_WIDE = "https://www.jma.go.jp/bosai/tgv/data/GSMWide"
    MSM_WIDE = "https://www.jma.go.jp/bosai/tgv/data/MSMWide"
    MSM_NAR  = "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow"
    LFM_NAR  = "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow"

    gsm_items = [
        Item("300hPa",   GSM_WIDE, "300",  "3001000", 3, "GSM_300"),
        Item("300hPa-2", GSM_WIDE, "3002", "3101000", 3, "GSM_3002"),
        # ★増やすならここに追加
    ]

    msm_items = [
        Item("500hPa",   MSM_WIDE, "500",  "500000", 2, "MSM_500"),
        Item("500hPa-2", MSM_WIDE, "5002", "510000", 2, "MSM_5002"),
        Item("700hPa",   MSM_WIDE, "700",  "700000", 2, "MSM_700"),
        Item("8502",     MSM_NAR,  "8502", "860000", 2, "MSM_8502"),
        Item("050",      MSM_NAR,  "050",  "050200", 2, "MSM_050"),
        Item("sfc",      MSM_NAR, "sfc",  "000200", 2, "MSM_sfc"),
        Item("sfc-2",    MSM_NAR, "sfc2", "010200", 2, "MSM_sfc2"),
        # ★増やすならここに追加
    ]

    lfm_items = [
        Item("850hPa",   LFM_NAR, "850",  "850200", 2, "LFM_850"),
        Item("925hPa",   LFM_NAR, "925",  "920200", 2, "LFM_925"),
        Item("975hPa",   LFM_NAR, "975",  "970200", 2, "LFM_975"),
        Item("sfc",      LFM_NAR, "sfc",  "000200", 2, "LFM_sfc"),
        Item("sfc-2",    LFM_NAR, "sfc2", "010200", 2, "LFM_sfc2"),
        # ★増やすならここに追加
    ]

    return {
        "GSM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            init_step_hours=6,
            rjtd_minute=0,
            init_probe_item=gsm_items[0],
            ft_list=ft_list_gsm(),
            items=gsm_items,
        ),
        "MSM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=3,
            rjtd_minute=0,
            init_probe_item=msm_items[0],
            ft_list=ft_list_msm(),
            items=msm_items,
        ),
        "LFM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=6,
            rjtd_minute=0,
            init_probe_item=lfm_items[0],
            ft_list=ft_list_lfm(),
            items=lfm_items,
        ),
    }
