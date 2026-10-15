#!/usr/bin/env python3
"""聞く項目（question）を、いまある法案すべてについて作り直す（聞く順を変えたとき用・2026-10-15 ORID 化で作成）。

  .venv/bin/python -m scripts.redo_questions            # question がある法案すべて
  .venv/bin/python -m scripts.redo_questions 221-shu-1  # 指定した法案だけ

import_bills.py --redo-questions は取り込んだ会期の法案だけが対象なので、前の会期の法案も含めて作り直すときはこちら。
既定の聞き方（FALLBACK）になった法案は最後に一覧を出す。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import interview, llm  # noqa: E402
from app.store import connect, init_db  # noqa: E402


def main() -> int:
    init_db()
    c = connect()
    ids = sys.argv[1:] or [r[0] for r in c.execute("SELECT DISTINCT bill_id FROM question ORDER BY bill_id")]
    fallback = []
    for bid in ids:
        row = c.execute("SELECT * FROM bill WHERE id=?", (bid,)).fetchone()
        if not row:
            print(f"  {bid}: 法案が無い")
            continue
        b = dict(row)
        t0 = time.time()
        qs = interview.make_questions(b)
        if [t for _, t in qs] == [t.format(name=b["law_name"] or b["title"]) for _, t in interview.FALLBACK]:
            fallback.append(bid)
        with c:
            c.execute("DELETE FROM question WHERE bill_id=?", (bid,))
            for i, (k, t) in enumerate(qs, 1):
                c.execute("INSERT INTO question VALUES (?,?,?,?,?,datetime('now'))", (bid, i, k, t, llm.MODEL))
        print(f"  {bid} {len(qs)}問（{time.time() - t0:.0f}秒）: {qs[0][1][:50]}", flush=True)
    print(f"作り直し {len(ids)}本・既定の聞き方 {len(fallback)}本 {fallback}")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
