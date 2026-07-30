#!/usr/bin/env python
"""Fidelity screenshots at true CSS viewports (desktop 1440, mobile 390) via headless
Chrome (channel='chrome'). Reports horizontal overflow + console errors per shot.

Usage: uv run python _fidshot.py <path> <out-prefix> [--js '<snippet>'] [--wait <ms>] [--only desktop|mobile]
"""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4646"
OUTDIR = __file__.rsplit("/", 1)[0]


def main():
    path, out = sys.argv[1], sys.argv[2]
    js, wait, only = None, 1200, None
    args, i = sys.argv[3:], 0
    while i < len(args):
        if args[i] == "--js":
            js = args[i + 1]; i += 2
        elif args[i] == "--wait":
            wait = int(args[i + 1]); i += 2
        elif args[i] == "--only":
            only = args[i + 1]; i += 2
        else:
            i += 1

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for label, w in (("desktop", 1440), ("mobile", 390)):
            if only and label != only:
                continue
            ctx = browser.new_context(viewport={"width": w, "height": 900},
                                      device_scale_factor=2, is_mobile=(label == "mobile"))
            page = ctx.new_page()
            errs = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.goto(BASE + path, wait_until="networkidle")
            page.wait_for_timeout(wait)
            if js:
                page.evaluate(js); page.wait_for_timeout(wait)
            png = f"{OUTDIR}/{out}_{label}.png"
            page.screenshot(path=png, full_page=True)
            ov = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
            print(f"  {label} {w}px -> {png}  h-overflow:{ov}px  console-errs:{len(errs)}")
            for e in errs[:5]:
                print("     !", e[:140])
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
