#!/usr/bin/env python3
"""xb4g/giin の giin.sqlite から、いまの国会で審議中の法案を取り込み、聞く項目を作る。

  .venv/bin/python scripts/import_bills.py                 # 第222回・審議中（委員会で審査中を含む）
  .venv/bin/python scripts/import_bills.py --session 222 --no-questions

- 法案ID・要約（explain）・経過は giin のものをそのまま使う（数字・日付は giin で照合済み）。
- 要約が無い・照合で落ちた（explain_reject）法案は取り込まない（説明の無いままインタビューしない）。
- 聞く項目は、まだ無い法案だけ gemma4 で作る。作り直すときは --redo-questions。
- 審議が終わった法案は消さない（status を写すだけ。画面で「審議中」の一覧から外れる）。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import interview, llm  # noqa: E402
from app.store import connect, init_db  # noqa: E402

GIIN = os.environ.get("KHOUAN_GIIN_DB", "/home/kojima/work/xb4g/giin/data/giin.sqlite")
ACTIVE = ("委員会で審査中", "審議中")


def jdate(d):
    if not d:
        return ""
    y, m, dd = (d.split("-") + ["", "", ""])[:3]
    return f"{int(y)}年{int(m)}月{int(dd)}日"


def submitter(b):
    """giin lib/bills.php g_bill_submitter と同じ組み立て"""
    sub = re.sub(r"\s+", " ", b["submitter"] or "").strip()
    sub = re.sub(r"君 外(\d+)名", r"議員ほか\1名", sub)
    sub = re.sub(r"君$", "議員", sub)
    if b["kind_code"] == "shu":
        return (sub or "衆議院議員") + "が衆議院に"
    if b["kind_code"] == "san":
        return (sub or "参議院議員") + "が参議院に"
    return "内閣が国会に"


def sessions_text(b):
    s = [x for x in (b["sessions"] or "").split(",") if x]
    if len(s) <= 1:
        return f"第{int(b['session'])}回国会"
    return f"第{s[0]}回〜第{s[-1]}回国会（{len(s)}会期）"


def answer(b):
    """giin の g_bill_answer と同じ（数字と日付だけ。評価はしない）"""
    what = {"kaku": "法律案（内閣提出）", "shu": "法律案（衆法）", "san": "法律案（参法）", "yosan": "予算", "joyaku": "条約"}.get(b["kind_code"], "議案")
    head = (f"{b['title']}は、" + (f"{jdate(b['submitted'])}に" if b["submitted"] else "") + submitter(b) + f"提出した{what}です。"
            + (f"{sessions_text(b)}に出ています。" if "," in (b["sessions"] or "") else ""))
    st = b["status"]
    if st == "委員会で審査中":
        return head + f"いまの国会（第{int(b['session'])}回）で、委員会に付託されて審査中です。"
    if st == "審議中":
        return head + f"いまの国会（第{int(b['session'])}回）で審議中です。"
    return head + f"最新の状態は「{st}」です。"


def timeline(b):
    """giin の g_bill_timeline と同じ"""
    ev = []
    who = re.sub(r"が(衆|参)議院に$|が国会に$", "", submitter(b))
    where = {"shu": "（衆議院）", "san": "（参議院）"}.get(b["kind_code"], "")
    if b["submitted"]:
        ev.append([b["submitted"], "提出：" + who + where])
    houses = [("shu", "衆議院"), ("san", "参議院")] if (b["sen_first"] or "") != "参先議" else [("san", "参議院"), ("shu", "衆議院")]
    for h, hn in houses:
        if b[h + "_committee"]:
            if b[h + "_committee_date"]:
                ev.append([b[h + "_committee_date"], f"{hn} {b[h + '_committee']}：{b[h + '_committee_result'] or '審査'}"])
            elif b[h + "_committee_result"]:
                ev.append(["", f"{hn} {b[h + '_committee']}：{b[h + '_committee_result']}"])
        if b[h + "_plenary_result"]:
            ev.append([b[h + "_plenary_date"], f"{hn} 本会議：{b[h + '_plenary_result']}" + (f"（{b[h + '_plenary_mode']}）" if b[h + "_plenary_mode"] else "")])
    if b["promulgated"]:
        ev.append([b["promulgated"], "公布" + (f"（法律第{b['law_number']}号）" if b["law_number"] else "")])
    ev.sort(key=lambda x: x[0] or "9999")
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", type=int, default=222)
    ap.add_argument("--no-questions", action="store_true")
    ap.add_argument("--redo-questions", nargs="*", help="作り直す法案ID（指定なしで全部）")
    a = ap.parse_args()
    init_db()
    g = sqlite3.connect(f"file:{GIIN}?mode=ro", uri=True)
    g.row_factory = sqlite3.Row
    rows = g.execute("SELECT * FROM bill WHERE session=? ORDER BY id", (a.session,)).fetchall()
    c = connect()
    n_new, n_skip, ids = 0, 0, []
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for b in rows:
        ex = json.loads(b["explain"] or "[]") if b["explain"] else []
        known = c.execute("SELECT 1 FROM bill WHERE id=?", (b["id"],)).fetchone()
        if not known and (b["status"] not in ACTIVE or not ex or b["explain_reject"]):
            n_skip += 1
            continue
        ids.append(b["id"])
        n_new += not known
        with c:
            c.execute("""INSERT OR REPLACE INTO bill (id, session, title, law_name, kind, kind_code, submitter, submitted,
                         status, last_date, sessions, shu_committee, san_committee, url, summary_url, text_url,
                         explain, explain_source, answer, timeline, imported_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (b["id"], b["session"], b["title"], b["law_name"], b["kind"], b["kind_code"], b["submitter"], b["submitted"],
                       b["status"], b["last_date"], b["sessions"], b["shu_committee"], b["san_committee"], b["url"],
                       b["summary_url"], b["text_url"], json.dumps(ex, ensure_ascii=False), b["explain_source"],
                       answer(b), json.dumps(timeline(b), ensure_ascii=False), now))
            c.execute("DELETE FROM bill_speech WHERE bill_id=?", (b["id"],))
            for s in g.execute("SELECT * FROM bill_speech WHERE bill_id=? AND role<>'report'", (b["id"],)):
                c.execute("INSERT INTO bill_speech VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (s["bill_id"], s["speech_id"], s["date"], s["house"], s["meeting"], s["speaker"],
                           s["position"], s["role"], s["url"], s["excerpt"]))
    print(f"取り込み: {len(ids)}本（新規 {n_new}・対象外 {n_skip}）")
    if a.no_questions:
        return
    redo = set(a.redo_questions or []) if a.redo_questions is not None else set()
    if a.redo_questions is not None and not a.redo_questions:
        redo = set(ids)
    for bid in ids:
        have = c.execute("SELECT COUNT(*) FROM question WHERE bill_id=?", (bid,)).fetchone()[0]
        if have and bid not in redo:
            continue
        b = dict(c.execute("SELECT * FROM bill WHERE id=?", (bid,)).fetchone())
        t0 = time.time()
        qs = interview.make_questions(b)
        with c:
            c.execute("DELETE FROM question WHERE bill_id=?", (bid,))
            for i, (k, t) in enumerate(qs, 1):
                c.execute("INSERT INTO question VALUES (?,?,?,?,?,datetime('now'))", (bid, i, k, t, llm.MODEL))
        print(f"  {bid} 聞く項目 {len(qs)}問（{time.time() - t0:.0f}秒）: {qs[0][1][:40]}…")


if __name__ == "__main__":
    main()
