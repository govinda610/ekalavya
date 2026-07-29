#!/usr/bin/env python
"""Faithful live-app screenshots at true CSS viewports (desktop 1440, mobile 390).

Usage: uv run python _liveshot.py <path> <out-prefix> [--js '<snippet>'] [--wait <ms>]
Renders http://127.0.0.1:4646<path> at both widths using a real Chromium device
viewport (device-width media queries fire correctly, unlike chrome --window-size).
"""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4646"
OUTDIR = __file__.rsplit("/", 1)[0]


def main():
    path = sys.argv[1]
    out = sys.argv[2]
    js = None
    wait = 1200
    args = sys.argv[3:]
    i = 0
    while i < len(args):
        if args[i] == "--js":
            js = args[i + 1]; i += 2
        elif args[i] == "--wait":
            wait = int(args[i + 1]); i += 2
        else:
            i += 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, w in (("desktop", 1440), ("mobile", 390)):
            ctx = browser.new_context(
                viewport={"width": w, "height": 900},
                device_scale_factor=2,
                is_mobile=(label == "mobile"),
            )
            page = ctx.new_page()
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(wait)
            if js:
                page.evaluate(js)
                page.wait_for_timeout(wait)
            png = f"{OUTDIR}/{out}_{label}.png"
            page.screenshot(path=png, full_page=True)
            # measure horizontal overflow
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth")
            print(f"  {label} {w}px -> {png}  (h-overflow: {overflow}px)")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
