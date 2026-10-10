#!/usr/bin/env python3
"""公開に同意された意見のまとめを、法案ごとに話題に束ねる（論点AIマップ kronten と同じ方式）。

  .venv/bin/python scripts/build_topics.py                 # 全法案。意見の組が前回と同じなら作り直さない
  .venv/bin/python scripts/build_topics.py --bill 222-san-1 --force
  .venv/bin/python scripts/build_topics.py --bill 222-san-1 --include-test   # 確認用（テストの意見も入れ、話題を is_test=1 で保存＝画面に出ない）

1. 埋め込み: intfloat/multilingual-e5-large（fastembed・手元の CPU。外部に送らない）。意見ごとに outputs/emb/ に保存し、次からは読み直す
2. まとめる: KMeans（random_state 固定。同じ材料なら毎回同じまとまり）
3. 名前・要約・論点: gemma4:12b-it-qat（0.3 の Ollama・think:false・JSON スキーマで型を縛る）。まとまり1つに1回だけ
4. 代表的な意見: 中心に近い順

公開された意見が MIN 件未満の法案は話題に分けない（画面では新しい順に並べる）。
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time

import numpy as np
from sklearn.cluster import KMeans

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import llm  # noqa: E402
from app.store import connect, init_db  # noqa: E402

EMBED = "intfloat/multilingual-e5-large"
CACHE = os.environ.get("FASTEMBED_CACHE_PATH", "/mnt/data/cache/fastembed")
EMB_DIR = os.path.join(ROOT, "outputs", "emb")
MIN = 5
_model = None


def opinion_text(r) -> str:
    reasons = "・".join(json.loads(r["reasons"] or "[]"))
    parts = [r["summary"], reasons, r["concerns"], r["proposals"]]
    return " ".join(p for p in parts if p)


def embed(rows) -> np.ndarray:
    """意見ごとに保存した埋め込みを読み、無いものだけ計算する（本文が変われば計算し直す）。"""
    global _model
    os.makedirs(EMB_DIR, exist_ok=True)
    out = [None] * len(rows)
    todo = []
    for i, r in enumerate(rows):
        t = opinion_text(r)
        p = os.path.join(EMB_DIR, f"{r['id']}-{hashlib.sha1(t.encode()).hexdigest()[:8]}.npy")
        if os.path.exists(p):
            out[i] = np.load(p)
        else:
            todo.append((i, t, p))
    if todo:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(EMBED, cache_dir=CACHE)
        vecs = list(_model.embed(["passage: " + t for _, t, _ in todo], batch_size=16))
        for (i, _, p), v in zip(todo, vecs):
            v = np.asarray(v) / np.linalg.norm(v)
            np.save(p, v)
            out[i] = v
    return np.vstack(out)


def choose_k(n: int) -> int:
    return max(2, min(8, round(math.sqrt(n / 2))))


SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string"}, "summary": {"type": "string"},
    "propositions": {"type": "array", "items": {"type": "string"}}},
    "required": ["name", "summary", "propositions"]}

PROMPT = """あなたは、法案について市民から寄せられた意見を整理する担当者です。
次の意見は、法案「{theme}」について、AIインタビューで寄せられ、本人が公開に同意した意見のうち、意味が近いものを集めた1つのまとまりです。

{samples}

このまとまりについて、JSON で返してください。
name には、何についての話題かを表す日本語の見出しを入れます。20字以内の体言止めにし、「〜について」は付けません。
summary には、このまとまりで言われていることの日本語の要約を入れます。80字以内で、意見に書かれていないことは足しません。
propositions には、賛成か反対かを問える論点の日本語の文を1〜2個入れます。各40字以内で「〜すべきだ」「〜である」の形にし、意見の中に根拠があるものだけにします。どちらかの立場に誘導する言葉は使いません。
"""


def label(theme, members):
    samples = "\n".join(f"- （{m['stance']}）{opinion_text(m)[:220]}" for m in members)
    d = llm.ask_json(PROMPT.format(theme=theme, samples=samples), SCHEMA, temperature=0, num_predict=900, timeout=600)
    raw = d.get("propositions") or []
    raw = raw if isinstance(raw, list) else [raw]
    return {"name": llm.text(d.get("name"))[:30], "summary": llm.text(d.get("summary"))[:160],
            "propositions": [t for t in (llm.text(p) for p in raw) if t][:2]}


def build_bill(c, b, include_test=False, force=False) -> dict:
    q = "SELECT * FROM report WHERE bill_id=? AND public=1" + ("" if include_test else " AND is_test=0") + " ORDER BY id"
    rows = [dict(r) for r in c.execute(q, (b["id"],))]
    test = 1 if include_test else 0
    if len(rows) < MIN:
        if not include_test:
            with c:  # 意見が減った（非公開に直した等）ときは古い話題を残さない
                for (tid,) in c.execute("SELECT id FROM topic WHERE bill_id=? AND is_test=0", (b["id"],)).fetchall():
                    c.execute("DELETE FROM topic_member WHERE topic_id=?", (tid,))
                c.execute("DELETE FROM topic WHERE bill_id=? AND is_test=0", (b["id"],))
        return {"bill": b["id"], "opinions": len(rows), "topics": 0, "skipped": f"{MIN}件未満"}
    have = sorted(r[0] for r in c.execute(
        "SELECT m.report_id FROM topic_member m JOIN topic t ON t.id=m.topic_id WHERE t.bill_id=? AND t.is_test=?", (b["id"], test)))
    if not force and have == sorted(r["id"] for r in rows):
        return {"bill": b["id"], "opinions": len(rows), "topics": None, "skipped": "変化なし"}
    t0 = time.time()
    E = embed(rows)
    k = min(choose_k(len(rows)), len(rows) // 2)
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(E)
    clusters = []
    for ci in range(k):
        idx = np.where(km.labels_ == ci)[0]
        order = idx[np.argsort(-(E[idx] @ km.cluster_centers_[ci]))]
        lab = label(b["title"], [rows[i] for i in order[:10]])
        clusters.append({**lab, "size": int(len(idx)), "members": [rows[i]["id"] for i in order]})
        print(f"  {b['id']} 話題 {ci + 1}/{k}: {lab['name']}（{len(idx)}件）", flush=True)
    clusters.sort(key=lambda x: -x["size"])
    now = time.strftime("%Y-%m-%d %H:%M")
    with c:
        for (tid,) in c.execute("SELECT id FROM topic WHERE bill_id=? AND is_test=?", (b["id"], test)).fetchall():
            c.execute("DELETE FROM topic_member WHERE topic_id=?", (tid,))
        c.execute("DELETE FROM topic WHERE bill_id=? AND is_test=?", (b["id"], test))
        for o, cl in enumerate(clusters, 1):
            cur = c.execute("INSERT INTO topic (bill_id, ord, name, summary, propositions, size, is_test, built_at) VALUES (?,?,?,?,?,?,?,?)",
                            (b["id"], o, cl["name"] or f"話題{o}", cl["summary"], json.dumps(cl["propositions"], ensure_ascii=False),
                             cl["size"], test, now))
            for rank, rid in enumerate(cl["members"]):
                c.execute("INSERT INTO topic_member VALUES (?,?,?)", (cur.lastrowid, rid, rank))
    out = os.path.join(ROOT, "outputs", "topics")
    os.makedirs(out, exist_ok=True)
    rec = {"bill": b["id"], "title": b["title"], "built_at": now, "is_test": test, "n": len(rows), "k": k,
           "embed_model": EMBED, "llm": llm.MODEL, "clusters": clusters}
    json.dump(rec, open(os.path.join(out, f"{b['id']}{'-test' if test else ''}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"bill": b["id"], "opinions": len(rows), "topics": k, "seconds": round(time.time() - t0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bill", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--include-test", action="store_true")
    a = ap.parse_args()
    init_db()
    c = connect()
    bills = [dict(r) for r in c.execute("SELECT * FROM bill ORDER BY id")]
    if a.bill:
        bills = [b for b in bills if b["id"] in a.bill]
    res = [build_bill(c, b, a.include_test, a.force) for b in bills]
    built = [r for r in res if r.get("topics")]
    print(json.dumps({"bills": len(res), "built": built,
                      "opinions": sum(r["opinions"] for r in res)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
