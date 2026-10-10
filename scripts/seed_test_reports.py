#!/usr/bin/env python3
"""話題づけと合意形成AIへの受け渡しを確かめるための、テストの意見を API 経由で作る（確認用・本番の材料にしない）。

  .venv/bin/python scripts/seed_test_reports.py 222-san-1 [--api http://127.0.0.1:18395]

作ったまとめはすぐ is_test=1 にする（公開の一覧・話題・合意形成AIの本番の論点には出ない）。確かめ終わったら
  .venv/bin/python scripts/admin.py delete-test
"""
import argparse
import json
import subprocess
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEOPLE = [
    ["【テスト】賛成です。", "【テスト】旧姓のまま研究論文を出し続けたいからです。", "【テスト】論文の著者名が途中で変わらずに済みます。", "【テスト】特にない", "【テスト】大学の事務でも旧姓を使えるようにしてほしい。"],
    ["【テスト】反対です。", "【テスト】通称を広げるより、選択的夫婦別姓を認めるべきだと思うからです。", "【テスト】自分には直接の影響はありません。", "【テスト】二つの名前の管理が続き、根本的な解決にならないことが心配です。", "【テスト】選択的夫婦別姓の議論を進めてほしい。"],
    ["【テスト】どちらかといえば反対です。", "【テスト】企業の人事や給与の事務が複雑になるからです。", "【テスト】人事担当として、システムの改修が必要になります。", "【テスト】中小企業に改修の費用がかかることが心配です。", "【テスト】改修の費用を国が支援してほしい。"],
    ["【テスト】賛成です。", "【テスト】銀行口座やパスポートで旧姓が使えると便利だからです。", "【テスト】海外出張のときに名前の違いで困らなくなります。", "【テスト】特にない", "【テスト】パスポートの旧姓併記をもっと簡単にしてほしい。"],
    ["【テスト】分からないです。", "【テスト】法案の中身がまだよく分からないからです。", "【テスト】分からない", "【テスト】戸籍の制度との関係がはっきりしないことが心配です。", "【テスト】国会でていねいに説明してほしい。"],
]


def post(api, path, body=None):
    req = urllib.request.Request(api + path, data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bill")
    ap.add_argument("--api", default="http://127.0.0.1:18395/api/")
    a = ap.parse_args()
    ids = []
    for ans in PEOPLE:
        s = post(a.api, "interview/start", {"bill_id": a.bill})
        sid, i, done = s["session_id"], 0, False
        while not done:
            d = post(a.api, f"interview/{sid}/answer", {"text": ans[min(i, len(ans) - 1)] if i < len(ans) else "【テスト】特にありません。"})
            done = d["done"]
            i += 1
        r = post(a.api, f"interview/{sid}/report")["draft"]
        sv = post(a.api, f"interview/{sid}/save", {"summary": r["summary"], "want_public": True, "consent": True})
        ids.append(sv["report_id"])
        print(sv["report_id"], sv["public"], r["stance"], r["summary"])
    subprocess.run([os.path.join(ROOT, ".venv/bin/python"), os.path.join(ROOT, "scripts/admin.py"), "mark-test", *ids], check=True)


if __name__ == "__main__":
    main()
