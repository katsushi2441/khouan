#!/usr/bin/env python3
"""法案ごとの話題から立てた論点を、Kurage 合意形成AI（kconsensus）の論点として渡す。kronten の to_kconsensus.py と同じ型。

  .venv/bin/python scripts/to_kconsensus.py                       # 話題のある法案すべて（渡す候補を見るだけ）
  .venv/bin/python scripts/to_kconsensus.py --apply               # 書き込み、賛否の読み取りまで
  .venv/bin/python scripts/to_kconsensus.py --bill 222-san-1 --include-test --apply   # 確認用（slug は khouan-test-<法案ID>）

- 合意形成AIの論点（topic）は法案ごとに1つ。slug は khouan-<法案ID>。
- 既にある論点と「ほぼ同じ文」（埋め込みの近さ SIM 以上）は渡さない。同じ主張かどうか・賛否を問える政策の文かは gemma4 で判定する
  （e5 は数字の違いを見分けられない。kronten 2026-10-08 の教訓）。source='khouan'、origin='interview'。
- 公開に同意された意見のまとめを、合意形成AIの reaction（platform='AIインタビュー'）として入れ、
  賛否の読み取りは kconsensus 側の scripts/import_reactions.py --fill に任せる（判定器も精度の表示も kconsensus のもの）。
- 合意形成AIの DB に書くと即本番。
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import llm  # noqa: E402
from app.pages import BASE  # noqa: E402
from app.store import connect, init_db  # noqa: E402

KC = os.environ.get("KHOUAN_KCONSENSUS", "/home/kojima/work/kconsensus")
KDB = os.path.join(KC, "data", "kconsensus.sqlite")
SIM = 0.995

CHECK = {"type": "object", "properties": {
    "policy": {"type": "boolean"}, "same_as": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["policy", "same_as", "reason"]}


def check(theme, cand, have):
    lst = "\n".join(f"{i}. {t}" for i, t in enumerate(have, 1)) or "（まだありません）"
    prompt = (f"テーマ: 法案「{theme}」\n\n既にある論点:\n{lst}\n\n新しい論点の候補: {cand}\n\n"
              "policy には、この候補がこの法案やその政策について、人が賛成か反対かを選べる文なら true、"
              "法案と関係がない、または賛否を選べない文なら false を入れます。\n"
              "same_as には、既にある論点のどれかと同じ主張なら、その番号を入れます。対象・範囲・手段が違えば別の主張です。"
              "同じものが無ければ 0 を入れます。\nreason には、判断の理由を30字以内で入れます。")
    try:
        return llm.ask_json(prompt, CHECK, temperature=0, num_predict=200, timeout=300)
    except llm.LLMError:
        return {"policy": False, "same_as": 0, "reason": "判定できず"}


def embed_texts(texts):
    from fastembed import TextEmbedding
    from scripts import build_topics
    if build_topics._model is None:
        build_topics._model = TextEmbedding(build_topics.EMBED, cache_dir=build_topics.CACHE)
    e = np.array(list(build_topics._model.embed(["passage: " + t for t in texts], batch_size=16)))
    return e / np.linalg.norm(e, axis=1, keepdims=True)


def handoff(c, kc, b, test, max_n, apply):
    tsql = "SELECT * FROM topic WHERE bill_id=? AND is_test=? ORDER BY ord"
    topics = [dict(t) for t in c.execute(tsql, (b["id"], int(test)))]
    if not topics:
        return None
    slug = f"khouan-{'test-' if test else ''}{b['id']}"
    name = b["law_name"] or b["title"]
    lead = (f"第{b['session']}回国会で{b['status']}の「{b['title']}」について、Kurage 法案AIインタビューで公開に同意された意見を話題に分け、"
            f"話題から賛否を問える論点を立てました。法案の解説とインタビューは {BASE}/b/{b['id']}/")
    row = kc.execute("SELECT id FROM topic WHERE slug=?", (slug,)).fetchone()
    have = [r[0] for r in kc.execute("SELECT text FROM statement WHERE topic_id=?", (row[0],))] if row else []
    cands = []
    for t in topics:
        for p in json.loads(t["propositions"] or "[]"):
            cands.append({"text": p.rstrip("。")[:100], "topic": t["name"], "size": t["size"], "ord": t["ord"]})
    picked = []
    if cands:
        E = embed_texts([x["text"] for x in cands] + have)
        ce, he = E[:len(cands)], E[len(cands):]
        for i, x in enumerate(cands):
            near = float((he @ ce[i]).max()) if len(he) else 0
            dup = max([float(ce[j] @ ce[i]) for j in picked] or [0])
            x["ok"] = near < SIM and dup < SIM
            if x["ok"]:
                chk = check(b["title"], x["text"], have + [cands[j]["text"] for j in picked])
                x["why"] = llm.text(chk.get("reason"))
                x["ok"] = chk.get("policy") is True and not chk.get("same_as")
            if x["ok"]:
                picked.append(i)
    # 押す側の負担を増やしすぎないよう、1つの法案の論点は合わせて12本まで
    send = sorted([cands[i] for i in picked], key=lambda x: -x["size"])[:max(0, min(max_n, 12 - len(have)))]
    for x in cands:
        print(f"  {'渡す' if x in send else '渡さない'} {x['text']}（{x['topic']}・{x['size']}件）{('｜' + x.get('why', '')) if x.get('why') else ''}")
    q = "SELECT * FROM report WHERE bill_id=? AND public=1" + ("" if test else " AND is_test=0")
    reps = [dict(r) for r in c.execute(q, (b["id"],))]
    if not apply:
        return {"bill": b["id"], "slug": slug, "send": len(send), "reactions": len(reps), "applied": False}
    with kc:
        if not row:
            kc.execute("INSERT INTO topic (slug, tracker, name, lead, updated_at) VALUES (?,?,?,?,datetime('now'))",
                       (slug, "", name, lead))
            row = kc.execute("SELECT id FROM topic WHERE slug=?", (slug,)).fetchone()
        else:
            kc.execute("UPDATE topic SET name=?, lead=?, updated_at=datetime('now') WHERE id=?", (name, lead, row[0]))
        tid = row[0]
        for x in send:
            kc.execute("INSERT INTO statement (topic_id, text, origin, basis, source, created_at) VALUES (?,?,?,?, 'khouan', datetime('now'))",
                       (tid, x["text"], "interview", f"法案AIインタビューの話題「{x['topic']}」（{x['size']}件）から {BASE}/b/{b['id']}/"))
        # 出典: 国会の質疑・答弁（giin から写したもの）と、インタビューの意見の置き場
        kc.execute("DELETE FROM evidence WHERE topic_id=?", (tid,))
        for s in c.execute("SELECT * FROM bill_speech WHERE bill_id=? ORDER BY date DESC LIMIT 24", (b["id"],)):
            kc.execute("INSERT INTO evidence (topic_id, kind, date, who, affiliation, body, url) VALUES (?,?,?,?,?,?,?)",
                       (tid, "diet", s["date"], s["speaker"], s["position"] or "", (s["excerpt"] or "")[:420], s["url"]))
        kc.execute("INSERT INTO evidence (topic_id, kind, date, who, affiliation, body, url) VALUES (?,?,?,?,?,?,?)",
                   (tid, "interview", "", "Kurage 法案AIインタビュー", "公開に同意された意見",
                    f"公開に同意された意見のまとめ {len(reps)}件（話題 {len(topics)}つ）", f"{BASE}/b/{b['id']}/"))
        # 公開に同意された意見を reaction として入れる（賛否の読み取りは kconsensus の import_reactions.py --fill）
        kc.executescript("""CREATE TABLE IF NOT EXISTS reaction (
  id INTEGER PRIMARY KEY, topic_id INTEGER, platform TEXT, author TEXT, text TEXT,
  empathy INTEGER, negative INTEGER, url TEXT, article TEXT, UNIQUE (topic_id, platform, author, text));
CREATE TABLE IF NOT EXISTS reaction_stance (reaction_id INTEGER, statement_id INTEGER, value INTEGER, model TEXT, created_at TEXT,
  PRIMARY KEY (reaction_id, statement_id));""")
        for r in reps:
            reasons = "・".join(json.loads(r["reasons"] or "[]"))
            text = "".join(f"{k}{v}" for k, v in (("立場：", r["stance"]), ("。", r["summary"]), (" 理由：", reasons),
                                                  (" 懸念：", r["concerns"]), (" 提案：", r["proposals"])) if v)[:520]
            kc.execute("INSERT OR IGNORE INTO reaction (topic_id, platform, author, text, empathy, negative, url, article) VALUES (?,?,?,?,?,?,?,?)",
                       (tid, "AIインタビュー", r["id"], text, 0, 0, f"{BASE}/r/{r['id']}", b["title"][:160]))
        # 非公開に直された・消された意見は、読み取りごと外す（author に意見のまとめの ID を入れている）
        ids = {r["id"] for r in reps}
        for rid, author in kc.execute("SELECT id, author FROM reaction WHERE topic_id=? AND platform='AIインタビュー'", (tid,)).fetchall():
            if author not in ids:
                kc.execute("DELETE FROM reaction_stance WHERE reaction_id=?", (rid,))
                kc.execute("DELETE FROM reaction WHERE id=?", (rid,))
    n_stmt = kc.execute("SELECT COUNT(*) FROM statement WHERE topic_id=?", (tid,)).fetchone()[0]
    p = subprocess.run(["/usr/bin/python3", "scripts/import_reactions.py", "--slug", slug, "--fill"], cwd=KC,
                       capture_output=True, text=True, timeout=3600,
                       env={**os.environ, "KCONSENSUS_OLLAMA": llm.OLLAMA, "PYTHONPATH": KC})
    tail = (p.stdout.strip().splitlines() or [""])[-1] if p.returncode == 0 else "error: " + p.stderr[-400:]
    print(f"  読み取り（kconsensus import_reactions --fill）: {tail}")
    if not test:
        with c:
            c.execute("INSERT OR REPLACE INTO handoff (bill_id, kconsensus_slug, statements, reactions, at) VALUES (?,?,?,?,datetime('now','localtime'))",
                      (b["id"], slug, n_stmt, len(reps)))
    return {"bill": b["id"], "slug": slug, "send": len(send), "statements": n_stmt, "reactions": len(reps), "reading": tail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bill", nargs="*")
    ap.add_argument("--max", type=int, default=6, help="1回に渡す論点の上限")
    ap.add_argument("--include-test", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    init_db()
    c = connect()
    kc = sqlite3.connect(KDB, timeout=30)
    bills = [dict(r) for r in c.execute("SELECT * FROM bill ORDER BY id")]
    if a.bill:
        bills = [b for b in bills if b["id"] in a.bill]
    out = [r for r in (handoff(c, kc, b, a.include_test, a.max, a.apply) for b in bills) if r]
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
