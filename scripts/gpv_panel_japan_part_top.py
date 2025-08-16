# -*- coding: utf-8 -*-
# scripts/gpv_panel_japan_part_top.py
from module.japan_panels import render_japan_panels

def main():
    render_japan_panels(part="top",
                        ncols=6, dpi=110, max_pages=0, output_dir="output")

if __name__ == "__main__":
    main()
