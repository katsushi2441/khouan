#!/usr/bin/env python3
"""ページを端末幅で撮り、横はみ出し（scrollWidth）を数字で確かめる。使い捨てのブラウザ（chrome-profile は使わない）。

  /usr/bin/python3 scripts/shot.py <名前> <URL> [--widths 320 360 390 1280] [--full] [--selector '#id']

→ outputs/shots/<名前>-<幅>.png
"""
import argparse
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("url")
    ap.add_argument("--widths", nargs="+", type=int, default=[320, 360, 390, 1280])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--selector", help="この要素から下だけを撮る（枠の確認用）")
    ap.add_argument("--until", help="--selector からこの要素の手前までを切り出す")
    a = ap.parse_args()
    out = os.path.join(ROOT, "outputs", "shots")
    os.makedirs(out, exist_ok=True)
    bad = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w in a.widths:
            pg = b.new_page(viewport={"width": w, "height": 900})
            pg.goto(a.url, wait_until="networkidle", timeout=60000)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            f = os.path.join(out, f"{a.name}-{w}.png")
            if a.selector and a.until:
                y0 = pg.evaluate(f"document.querySelector({a.selector!r}).getBoundingClientRect().top + scrollY - 12")
                y1 = pg.evaluate(f"document.querySelector({a.until!r}).getBoundingClientRect().top + scrollY - 4")
                pg.screenshot(path=f, full_page=True, clip={"x": 0, "y": y0, "width": w, "height": y1 - y0})
            elif a.selector:
                pg.evaluate(f"""(() => {{ const el = document.querySelector({a.selector!r}); if (el) window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 10); }})()""")
                pg.screenshot(path=f, full_page=False)
            else:
                pg.screenshot(path=f, full_page=a.full)
            ok = sw <= w
            bad += not ok
            print(f"{w}px scrollWidth={sw} {'OK' if ok else 'はみ出し'} → {f}")
            pg.close()
        b.close()
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
