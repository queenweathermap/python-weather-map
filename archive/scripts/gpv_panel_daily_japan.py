# -*- coding: utf-8 -*-
# scripts/gpv_panel_daily_japan.py

from __future__ import annotations
import os, argparse

from module.japan_panels import render_japan_panels


def _envint(k: str, d: int) -> int:
    try:
        return int(os.environ.get(k, str(d)))
    except Exception:
        return d


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Japan weather panels generator")
    p.add_argument("--part", choices=["top", "bottom"], default=None,
                   help="top: 上3段, bottom: 下3段（省略で全段）")
    p.add_argument("--ncols", type=int, default=_envint("PANEL_NCOLS", 6))
    p.add_argument("--dpi", type=int, default=_envint("PANEL_DPI", 110))
    p.add_argument("--max_pages", type=int, default=_envint("PANEL_MAX_PAGES", 0))
    p.add_argument("--output_dir", default=os.environ.get("OUTPUT_DIR", "output"))
    return p


def main():
    ap = build_arg_parser()
    args = ap.parse_args()

    saved = render_japan_panels(
        part=args.part,
        ncols=args.ncols,
        dpi=args.dpi,
        max_pages=args.max_pages,
        output_dir=args.output_dir,
    )
    print("[OK] saved:", *saved, sep="\n  ")


if __name__ == "__main__":
    main()
