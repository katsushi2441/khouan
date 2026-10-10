#!/usr/bin/env python3
"""公開URLのインタビュー画面を、使い捨てのブラウザ（Playwright・chrome-profile は使わない）で最後まで通す確認。

  /usr/bin/python3 scripts/e2e_interview.py 222-san-1 [--width 390] [--private]

テストと分かる答えを送り、まとめを「公開してよい」で保存する。保存したまとめは、このあと
  .venv/bin/python scripts/admin.py mark-test <report_id>   → 確かめ終わったら delete-test
で公開の一覧から外し、消す。画面は outputs/shots/e2e-*.png に残す。
"""
import argparse
import os
import re
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://kurage.exbridge.jp/khouan.php"
ANSWERS = [
    "【動作確認のテスト回答です】どちらかといえば賛成です。",
    "【テスト】結婚で姓が変わっても、仕事では旧姓を使い続けられたほうが取引先とのやりとりで混乱が少ないからです。",
    "【テスト】資格の登録証や名刺を旧姓のままにできると、手続きの手間が減ると思います。",
    "【テスト】職場では旧姓、役所では戸籍の姓と、二つの名前を使い分ける事務の負担が増えないかが心配です。",
    "【テスト】銀行や病院などで本人確認をするときに、どちらの姓でも確認できる仕組みを整えてほしいです。",
    "【テスト】導入の前に、企業や自治体向けに分かりやすい手引きを出してほしいです。",
    "【テスト】以上です。",
    "【テスト】特にありません。",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bill")
    ap.add_argument("--width", type=int, default=390)
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args()
    out = os.path.join(ROOT, "outputs", "shots")
    os.makedirs(out, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": a.width, "height": 860})
        pg.goto(f"{BASE}/b/{a.bill}/interview")
        pg.check("#agree0")
        pg.click("#start")
        pg.wait_for_selector("#talk:not(.hide)", timeout=60000)
        t0 = time.time()
        for i, ans in enumerate(ANSWERS):
            if pg.is_visible("#rep") or pg.locator("#compose").get_attribute("class") == "compose hide":
                break
            n_ai = pg.locator(".msg.ai").count()
            q = pg.locator(".msg.ai").last.inner_text().split("\n", 1)[-1]
            print(f"Q{i + 1}: {q}\nA{i + 1}: {ans}")
            pg.fill("#ans", ans)
            pg.click("#send")
            # 次の質問か、まとめのどちらかが出るまで待つ
            pg.wait_for_function(f"document.querySelectorAll('.msg.ai').length > {n_ai} || !document.querySelector('#rep').classList.contains('hide') || document.querySelector('#compose').classList.contains('hide')", timeout=120000)
        pg.wait_for_selector("#rep:not(.hide)", timeout=180000)
        print(f"まとめ: 立場={pg.inner_text('#r-stance')} 要点={pg.input_value('#r-summary')}")
        print("その他:", pg.inner_text("#r-more").replace("\n", " / "))
        pg.screenshot(path=os.path.join(out, f"e2e-report-{a.width}.png"), full_page=True)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        pg.check("input[name=pub][value='0']" if a.private else "input[name=pub][value='1']")
        pg.check("#consent")
        pg.click("#save")
        pg.wait_for_selector("#fin:not(.hide)", timeout=120000)
        msg = pg.inner_text("#fin-msg")
        url = pg.get_attribute("#fin-link", "href")
        print(f"保存: {msg}\nURL: {url}\n所要 {time.time() - t0:.0f}秒・scrollWidth={sw}（幅{a.width}）")
        rid = re.search(r"/r/([0-9a-f]+)", url).group(1)
        pg.goto(url)
        pg.screenshot(path=os.path.join(out, f"e2e-saved-{a.width}.png"), full_page=True)
        print("REPORT_ID", rid)
        b.close()


if __name__ == "__main__":
    main()
