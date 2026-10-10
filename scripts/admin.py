#!/usr/bin/env python3
"""管理用（手で動かす）。

  .venv/bin/python scripts/admin.py list                       # 意見のまとめの一覧（公開・非公開・判定）
  .venv/bin/python scripts/admin.py mark-test <report_id>...   # 確認用のまとめをテストにする（公開の一覧・話題・合意形成AIから外れる）
  .venv/bin/python scripts/admin.py hide <report_id>...        # 公開を取り下げる（荒らしの見逃しなど）
  .venv/bin/python scripts/admin.py delete-test                # テストのまとめ・セッション・話題と、合意形成AIの khouan-test-* を消す
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.store import connect, init_db  # noqa: E402

KDB = os.path.join(os.environ.get("KHOUAN_KCONSENSUS", "/home/kojima/work/kconsensus"), "data", "kconsensus.sqlite")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    init_db()
    c = connect()
    if cmd == "list":
        for r in c.execute("SELECT id, bill_id, stance, public, want_public, moderation, moderation_reason, is_test, created_at, summary FROM report ORDER BY created_at"):
            print(" | ".join(str(x) for x in r))
    elif cmd == "mark-test":
        with c:
            for rid in args:
                c.execute("UPDATE report SET is_test=1 WHERE id=?", (rid,))
                c.execute("UPDATE session SET is_test=1 WHERE id=(SELECT session_id FROM report WHERE id=?)", (rid,))
        print("テストにしました:", args)
    elif cmd == "hide":
        with c:
            for rid in args:
                c.execute("UPDATE report SET public=0, moderation='hidden', moderation_reason='管理者が取り下げ' WHERE id=?", (rid,))
        print("取り下げました:", args, "（話題と合意形成AIからは、次の定期処理で外れます）")
    elif cmd == "delete-test":
        sids = [r[0] for r in c.execute("SELECT session_id FROM report WHERE is_test=1")] + \
               [r[0] for r in c.execute("SELECT id FROM session WHERE is_test=1")]
        with c:
            for (tid,) in c.execute("SELECT id FROM topic WHERE is_test=1").fetchall():
                c.execute("DELETE FROM topic_member WHERE topic_id=?", (tid,))
            n_t = c.execute("DELETE FROM topic WHERE is_test=1").rowcount
            n_r = c.execute("DELETE FROM report WHERE is_test=1").rowcount
            for s in set(sids):
                c.execute("DELETE FROM message WHERE session_id=?", (s,))
                c.execute("DELETE FROM session WHERE id=?", (s,))
        kc = sqlite3.connect(KDB, timeout=30)
        n_k = 0
        with kc:
            for (tid,) in kc.execute("SELECT id FROM topic WHERE slug LIKE 'khouan-test-%'").fetchall():
                kc.execute("DELETE FROM reaction_stance WHERE reaction_id IN (SELECT id FROM reaction WHERE topic_id=?)", (tid,))
                kc.execute("DELETE FROM reaction WHERE topic_id=?", (tid,))
                kc.execute("DELETE FROM vote WHERE statement_id IN (SELECT id FROM statement WHERE topic_id=?)", (tid,))
                kc.execute("DELETE FROM statement WHERE topic_id=?", (tid,))
                kc.execute("DELETE FROM evidence WHERE topic_id=?", (tid,))
                kc.execute("DELETE FROM topic WHERE id=?", (tid,))
                n_k += 1
        print(f"消しました: まとめ {n_r}件・セッション {len(set(sids))}件・話題 {n_t}件・合意形成AIの論点 {n_k}件")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
