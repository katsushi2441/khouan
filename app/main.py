#!/usr/bin/env python3
"""Kurage 法案AIインタビュー（khouan）

国会で審議中の法案を解説し、AIインタビューで意見を聞き、公開に同意された意見を話題に束ね、
合意形成AI（kconsensus）へ論点として渡す。公開は heteml の khouan.php が中継する。

- ログインなし。氏名は聞かない。IP は塩つきハッシュで回数の上限にだけ使う。
- 意見のまとめは、本人が確かめて同意したときだけ保存する。公開も本人が選ぶ。
- 公開を選んでも、決まった形の個人情報（電話・メール・URL 等）と gemma4 の判定（悪口・個人情報・宣伝）に
  かかったものは公開しない。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import amend, ask, interview, llm, pages
from .store import connect, init_db

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _env() -> dict:
    e = {}
    p = ROOT / ".env"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                e[k.strip()] = v.strip().strip('"\'')
    return e


ENV = _env()
RELAY_TOKEN = os.environ.get("KHOUAN_RELAY_TOKEN") or ENV.get("KHOUAN_RELAY_TOKEN", "")
SALT = os.environ.get("KHOUAN_SALT") or ENV.get("KHOUAN_SALT", "khouan")
BASE = pages.BASE
KC_BASE = "https://kurage.exbridge.jp/kconsensus.php/t/"

MAX_ANSWER = 600
MAX_TURNS = 14            # 1回のインタビューで答える回数の上限
MAX_FOLLOWUPS = 3         # AI が深掘りする回数の上限
LIMITS = {                # 回線（IP のハッシュ）ごとの上限: (秒, 回数)
    "start": [(3600, 6), (86400, 20)],
    "answer": [(3600, 90)],
    "report": [(3600, 12)],
    "save": [(3600, 6), (86400, 20)],
    "amend_draft": [(3600, 10), (86400, 40)],   # 条文への修正提案：AIで形に整える
    "amend_save": [(3600, 6), (86400, 20)],     # 条文への修正提案：保存
    "ask": [(3600, 20), (86400, 60)],           # 法案について質問する（2026-10-16）
}
GLOBAL_START_PER_HOUR = 300   # 全体の上限（0.3 の GPU を守る）
SESSION_TTL = 3 * 3600

app = FastAPI(title="Kurage 法案AIインタビュー", docs_url=None, redoc_url=None, openapi_url=None)
init_db()


def _ip(req: Request) -> str:
    """中継（khouan.php）が合言葉つきで渡したときだけ X-Forwarded-For を信じる。直接来たら接続元。"""
    if RELAY_TOKEN and req.headers.get("x-khouan-relay") == RELAY_TOKEN:
        xff = req.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return req.client.host if req.client else "?"


def _hash(ip: str) -> str:
    return hashlib.sha256((SALT + "|" + ip).encode()).hexdigest()[:20]


def _limit(c, iph: str, kind: str) -> None:
    now = time.time()
    for sec, n in LIMITS[kind]:
        k = c.execute("SELECT COUNT(*) FROM hit WHERE ip_hash=? AND kind=? AND at>?", (iph, kind, now - sec)).fetchone()[0]
        if k >= n:
            raise HTTPException(429, "回数の上限に達しました。時間をおいてからもう一度お試しください。")
    if kind == "start":
        k = c.execute("SELECT COUNT(*) FROM hit WHERE kind='start' AND at>?", (now - 3600,)).fetchone()[0]
        if k >= GLOBAL_START_PER_HOUR:
            raise HTTPException(429, "いま混み合っています。時間をおいてからもう一度お試しください。")
    with c:
        c.execute("INSERT INTO hit (ip_hash, kind, at) VALUES (?,?,?)", (iph, kind, now))
        c.execute("DELETE FROM hit WHERE at<?", (now - 2 * 86400,))


def _bill(c, bid: str) -> dict:
    b = c.execute("SELECT * FROM bill WHERE id=?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404, "その法案は取り込んでいません")
    return dict(b)


def _questions(c, bid: str) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT ord, kind, text FROM question WHERE bill_id=? ORDER BY ord", (bid,))]


def _public_reports(c, bid: str, limit: int = 0) -> list[dict]:
    q = "SELECT * FROM report WHERE bill_id=? AND public=1 AND is_test=0 ORDER BY created_at DESC"
    return [dict(r) for r in c.execute(q + (f" LIMIT {int(limit)}" if limit else ""), (bid,))]


def _topics(c, bid: str, examples: int = 3) -> list[dict]:
    out = []
    for t in c.execute("SELECT * FROM topic WHERE bill_id=? AND is_test=0 ORDER BY ord", (bid,)):
        t = dict(t)
        t["propositions"] = json.loads(t["propositions"] or "[]")
        t["examples"] = [dict(r) for r in c.execute(
            """SELECT r.id, r.summary, r.stance FROM topic_member m JOIN report r ON r.id=m.report_id
               WHERE m.topic_id=? AND r.public=1 AND r.is_test=0 ORDER BY m.rank LIMIT ?""", (t["id"], examples))]
        out.append(t)
    return out


def _articles(c, bid: str) -> list[dict]:
    """条ごとに、公開された修正提案の件数をつけて"""
    return [dict(r) for r in c.execute(
        """SELECT a.*, (SELECT COUNT(*) FROM amendment m WHERE m.bill_id=a.bill_id AND m.ord=a.ord AND m.public=1 AND m.is_test=0) n_public
           FROM article a WHERE a.bill_id=? ORDER BY a.ord""", (bid,))]


def _article(c, bid: str, ord_: int) -> dict:
    a = c.execute("SELECT * FROM article WHERE bill_id=? AND ord=?", (bid, ord_)).fetchone()
    if not a:
        raise HTTPException(404, "その条は取り込んでいません")
    return dict(a)


def _kc_url(c, bid: str) -> str | None:
    r = c.execute("SELECT kconsensus_slug FROM handoff WHERE bill_id=? AND statements>0", (bid,)).fetchone()
    return f"{KC_BASE}{r[0]}/" if r else None


# ── 画面 ────────────────────────────────────────────

ACTIVE = ("委員会で審査中", "審議中")


@app.get("/", response_class=HTMLResponse)
def index(q: str = ""):
    c = connect()
    rows = [dict(r) for r in c.execute(
        f"""SELECT b.*, (SELECT COUNT(*) FROM report r WHERE r.bill_id=b.id AND r.public=1 AND r.is_test=0) n_public,
                   (SELECT COUNT(*) FROM topic t WHERE t.bill_id=b.id AND t.is_test=0) n_topics
            FROM bill b WHERE b.status IN ({','.join('?' * len(ACTIVE))})
            ORDER BY n_public DESC, b.last_date DESC, b.id""", ACTIVE)]
    c.close()
    q = q.strip()[:40]
    if q:
        rows = [b for b in rows if all(w in (b["title"] + (b["law_name"] or "")) for w in q.split())]
    return pages.index(rows, q)


@app.get("/about", response_class=HTMLResponse)
def about():
    c = connect()
    n = c.execute(f"SELECT COUNT(*) FROM bill WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE).fetchone()[0]
    c.close()
    return pages.about_page(n)


@app.get("/b/{bid}/", response_class=HTMLResponse)
def bill_page(bid: str):
    c = connect()
    b = _bill(c, bid)
    sp = [dict(r) for r in c.execute("SELECT * FROM bill_speech WHERE bill_id=? ORDER BY date DESC, speech_id DESC", (bid,))]
    pubs = _public_reports(c, bid)
    out = pages.bill_page(b, sp, _topics(c, bid), pubs[:10], len(pubs), _kc_url(c, bid), _articles(c, bid))
    c.close()
    return out


@app.get("/b/{bid}")
def bill_noslash(bid: str):
    return Response(status_code=302, headers={"Location": f"{BASE}/b/{bid}/"})


@app.get("/b/{bid}/interview", response_class=HTMLResponse)
def interview_page(bid: str):
    c = connect()
    b = _bill(c, bid)
    n = len(_questions(c, bid))
    c.close()
    if b["status"] not in ACTIVE:
        return HTMLResponse(pages.page("審議が終わった法案です", "", f"/b/{bid}/interview",
                                       f'<h1>この法案の審議は終わっています</h1><p><a href="{BASE}/b/{bid}/">法案ページへ</a></p>', noindex=True))
    return pages.interview_page(b, n)


@app.get("/r/{rid}", response_class=HTMLResponse)
def report_page(rid: str, k: str = ""):
    c = connect()
    r = c.execute("SELECT * FROM report WHERE id=?", (rid,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(404, "そのまとめはありません")
    r = dict(r)
    private = not r["public"]
    if private and not (k and r["view_key"] and secrets.compare_digest(k, r["view_key"])):
        c.close()
        return HTMLResponse(pages.page("公開されていないまとめです", "", f"/r/{rid}",
                                       f'<h1>このまとめは公開されていません</h1><p><a href="{BASE}/">法案の一覧へ</a></p>', noindex=True),
                            status_code=404)
    b = _bill(c, r["bill_id"])
    c.close()
    return pages.report_page(r, b, private)


@app.get("/b/{bid}/a/{ord_}", response_class=HTMLResponse)
def article_page(bid: str, ord_: int):
    c = connect()
    b = _bill(c, bid)
    a = _article(c, bid, ord_)
    arts = _articles(c, bid)
    ms = [dict(r) for r in c.execute("""SELECT * FROM amendment WHERE bill_id=? AND ord=? AND public=1 AND is_test=0
                                         ORDER BY created_at DESC""", (bid, ord_))]
    c.close()
    return pages.article_page(b, a, arts, ms, accepting=b["status"] in ACTIVE)


@app.get("/m/{mid}", response_class=HTMLResponse)
def amendment_page(mid: str, k: str = ""):
    c = connect()
    m = c.execute("SELECT * FROM amendment WHERE id=?", (mid,)).fetchone()
    if not m:
        c.close()
        raise HTTPException(404, "その提案はありません")
    m = dict(m)
    if not m["public"] and not (k and m["view_key"] and secrets.compare_digest(k, m["view_key"])):
        c.close()
        return HTMLResponse(pages.page("公開されていない提案です", "", f"/m/{mid}",
                                       f'<h1>この提案は公開されていません</h1><p><a href="{BASE}/">法案の一覧へ</a></p>', noindex=True),
                            status_code=404)
    b = _bill(c, m["bill_id"])
    a = _article(c, m["bill_id"], m["ord"])
    c.close()
    return pages.amendment_page(m, b, a, private=not m["public"])


@app.get("/ogp.png")
def ogp():
    return FileResponse(HERE / "static" / "ogp.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {BASE}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap():
    c = connect()
    rows = c.execute("""SELECT b.id, b.last_date, (SELECT MAX(substr(created_at,1,10)) FROM report r
                        WHERE r.bill_id=b.id AND r.public=1 AND r.is_test=0) last_op FROM bill b ORDER BY b.id""").fetchall()
    c.close()
    lm = lambda *d: max([x for x in d if x] or ["2026-10-11"])[:10]  # noqa: E731
    top = lm(*[lm(r[1], r[2]) for r in rows])
    urls = [(f"{BASE}/", top), (f"{BASE}/about", "2026-10-11")] + [(f"{BASE}/b/{r[0]}/", lm(r[1], r[2])) for r in rows]
    # 条のページは、公開された修正提案があるものだけ（中身の無いページを索引に出さない）
    c = connect()
    urls += [(f"{BASE}/b/{r[0]}/a/{r[1]}", lm(r[2])) for r in c.execute(
        """SELECT bill_id, ord, MAX(substr(created_at,1,10)) FROM amendment WHERE public=1 AND is_test=0 GROUP BY bill_id, ord""")]
    c.close()
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"<url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls) + "</urlset>\n")
    return Response(body, media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    c = connect()
    bills = c.execute(f"SELECT id, title FROM bill WHERE status IN ({','.join('?' * len(ACTIVE))}) ORDER BY id", ACTIVE).fetchall()
    c.close()
    lines = "\n".join(f"- [{t}]({BASE}/b/{i}/)" for i, t in bills)
    return f"""# Kurage 法案AIインタビュー

> 国会で審議中の法案（第222回国会）を国会の公開情報から解説し、AIインタビューで市民の意見を聞き、公開に同意された意見を法案ごとに話題に束ねるシステム。話題から立てた論点は Kurage 合意形成AI（合意点マップ）で賛否の割れ方と一致点を出す。株式会社エクスブリッジ（名古屋）。

## 注意
- 国会の公式の意見窓口ではない（公式の方法は請願）。
- 法案の要約は法律案の「理由」・議案要旨を生成AI（gemma4）が要約したもの。数字と日付は元の文と照合済み。
- 話題の件数は公開に同意された意見の数で、世論調査ではない。賛成・反対の割合を示すものではない。

## API（読み取り専用）
- {BASE}/api/bill/<法案ID>/summary : 公開された意見の件数、話題ごとの件数と代表的な意見、合意形成AIのページURL

## 法案（{len(bills)}本）
{lines}
"""


# ── API（公開・読み取り） ─────────────────────────────

def _cors(d: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(d, status_code=status, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


@app.get("/api/bills")
def api_bills():
    c = connect()
    rows = [{"id": r["id"], "title": r["title"], "status": r["status"], "url": f"{BASE}/b/{r['id']}/",
             "opinions": r["n"]} for r in c.execute(
        """SELECT b.id, b.title, b.status, (SELECT COUNT(*) FROM report r WHERE r.bill_id=b.id AND r.public=1 AND r.is_test=0) n
           FROM bill b ORDER BY b.id""")]
    c.close()
    return _cors({"bills": rows})


@app.get("/api/bill/{bid}/summary")
def api_summary(bid: str):
    c = connect()
    b = c.execute("SELECT * FROM bill WHERE id=?", (bid,)).fetchone()
    if not b:
        c.close()
        return _cors({"error": "その法案は取り込んでいません", "bill_id": bid}, 404)
    pubs = _public_reports(c, bid)
    tps = _topics(c, bid)
    d = {
        "bill_id": bid, "title": b["title"], "status": b["status"],
        "bill_url": f"{BASE}/b/{bid}/", "interview_url": f"{BASE}/b/{bid}/interview",
        "accepting": b["status"] in ACTIVE,
        "opinions": len(pubs),
        "topics": [{"name": t["name"], "summary": t["summary"], "size": t["size"],
                    "examples": [{"text": e["summary"], "url": f"{BASE}/r/{e['id']}"} for e in t["examples"][:2]]} for t in tps],
        "topics_built_at": tps[0]["built_at"] if tps else None,
        "recent": [] if tps else [{"text": r["summary"], "url": f"{BASE}/r/{r['id']}"} for r in pubs[:3]],
        "kconsensus_url": _kc_url(c, bid),
        "amendments": [{"article": a["label"], "heading": a["heading"], "proposals": a["n_public"],
                        "url": f"{BASE}/b/{bid}/a/{a['ord']}"} for a in _articles(c, bid) if a["n_public"]],
        "note": "件数は公開に同意された意見の数（世論調査ではない）。話題の名前と要約は生成AIによる。",
    }
    c.close()
    return _cors(d)


@app.get("/healthz")
def healthz():
    c = connect()
    n = c.execute("SELECT COUNT(*) FROM bill").fetchone()[0]
    r = c.execute("SELECT COUNT(*) FROM report").fetchone()[0]
    c.close()
    return {"ok": True, "bills": n, "reports": r}


# ── API（インタビュー） ───────────────────────────────

class Start(BaseModel):
    bill_id: str


class Answer(BaseModel):
    text: str


class Save(BaseModel):
    summary: str
    want_public: bool
    consent: bool


def _session(c, sid: str) -> dict:
    s = c.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
    if not s:
        raise HTTPException(404, "インタビューが見つかりません。最初からやり直してください。")
    s = dict(s)
    if time.time() - time.mktime(time.strptime(s["created_at"], "%Y-%m-%d %H:%M:%S")) > SESSION_TTL:
        raise HTTPException(410, "時間が経ったため、このインタビューは終わりました。最初からやり直してください。")
    return s


def _say(c, sid: str, role: str, qord: int, kind: str, text: str) -> None:
    c.execute("INSERT INTO message (session_id, role, qord, kind, text, created_at) VALUES (?,?,?,?,?,datetime('now','localtime'))",
              (sid, role, qord, kind, text))


@app.post("/api/interview/start")
def start(b: Start, req: Request):
    c = connect()
    try:
        bill = _bill(c, b.bill_id)
        if bill["status"] not in ACTIVE:
            raise HTTPException(400, "この法案の審議は終わっています")
        qs = _questions(c, b.bill_id)
        if not qs:
            raise HTTPException(503, "この法案の質問をまだ用意できていません")
        _limit(c, _hash(_ip(req)), "start")
        sid = secrets.token_urlsafe(18)
        hello = (f"こんにちは。{bill['title']}について、{len(qs)}問ほど聞かせてください。"
                 "答えたくない質問は「答えない」を押して飛ばせます。名前や連絡先は書かないでください。")
        with c:
            c.execute("INSERT INTO session (id, bill_id, ip_hash, state, created_at, updated_at) "
                      "VALUES (?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
                      (sid, b.bill_id, _hash(_ip(req)), "asking"))
            _say(c, sid, "ai", 0, "hello", hello)
            _say(c, sid, "ai", qs[0]["ord"], "base", qs[0]["text"])
        return {"session_id": sid, "messages": [{"text": hello}, {"text": qs[0]["text"]}],
                "progress": {"n": 0, "total": len(qs)}}
    finally:
        c.close()


@app.post("/api/interview/{sid}/answer")
def answer(sid: str, a: Answer, req: Request):
    text = " ".join(a.text.split())[:MAX_ANSWER + 1]
    if not text:
        raise HTTPException(400, "答えを書いてください")
    if len(text) > MAX_ANSWER:
        raise HTTPException(400, f"1回の答えは{MAX_ANSWER}字までです")
    c = connect()
    try:
        s = _session(c, sid)
        if s["state"] != "asking":
            raise HTTPException(400, "このインタビューはもう終わっています")
        if s["turns"] >= MAX_TURNS:
            raise HTTPException(400, "答えの回数の上限に達しました")
        _limit(c, s["ip_hash"], "answer")
        bill = _bill(c, s["bill_id"])
        qs = _questions(c, s["bill_id"])
        last = c.execute("SELECT * FROM message WHERE session_id=? AND role='ai' ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
        qi = s["q_index"]
        with c:
            _say(c, sid, "user", last["qord"], "answer", text)
        msgs, followups = [], s["followups"]
        skipped = text.startswith("答えない")
        # 深掘りは基本の質問への答えにだけ。深掘りへの答えには重ねない。
        # ORID の順（2026-10-15〜）では「理由」の質問が無いので、賛否の答えにも深掘り（そう考える理由）をかける
        if (last["kind"] == "base" and not skipped and followups < MAX_FOLLOWUPS):
            f = interview.follow_up(bill, last["text"], text)
            if f:
                msgs.append({"text": f})
                followups += 1
                with c:
                    _say(c, sid, "ai", last["qord"], "follow", f)
                    c.execute("UPDATE session SET followups=?, turns=turns+1, updated_at=datetime('now','localtime') WHERE id=?", (followups, sid))
                return {"messages": msgs, "done": False, "progress": {"n": qi, "total": len(qs)}}
        qi += 1
        done = qi >= len(qs)
        with c:
            if not done:
                _say(c, sid, "ai", qs[qi]["ord"], "base", qs[qi]["text"])
                msgs.append({"text": qs[qi]["text"]})
            c.execute("UPDATE session SET q_index=?, turns=turns+1, state=?, updated_at=datetime('now','localtime') WHERE id=?",
                      (qi, "done" if done else "asking", sid))
        return {"messages": msgs, "done": done, "progress": {"n": min(qi, len(qs)), "total": len(qs)}}
    finally:
        c.close()


@app.post("/api/interview/{sid}/report")
def report(sid: str):
    c = connect()
    try:
        s = _session(c, sid)
        if s["state"] == "saved":
            raise HTTPException(400, "このインタビューは保存済みです")
        if s["state"] != "done":
            raise HTTPException(400, "まだ質問が残っています")
        _limit(c, s["ip_hash"], "report")
        if s["draft"]:
            return {"draft": json.loads(s["draft"])}
        bill = _bill(c, s["bill_id"])
        log = [(r["role"], r["text"]) for r in c.execute(
            "SELECT role, text FROM message WHERE session_id=? AND kind<>'hello' ORDER BY id", (sid,))]
        try:
            d = interview.make_report(bill, log)
        except llm.LLMError:
            raise HTTPException(503, "まとめを作れませんでした（AIが混み合っています）")
        with c:
            c.execute("UPDATE session SET draft=?, updated_at=datetime('now','localtime') WHERE id=?",
                      (json.dumps(d, ensure_ascii=False), sid))
        return {"draft": d}
    finally:
        c.close()


@app.post("/api/interview/{sid}/save")
def save(sid: str, v: Save):
    if not v.consent:
        raise HTTPException(400, "保存への同意が必要です")
    summary = " ".join(v.summary.split())
    if not summary or len(summary) > 300:
        raise HTTPException(400, "要点は1〜300字で書いてください")
    c = connect()
    try:
        s = _session(c, sid)
        if s["state"] == "saved":
            raise HTTPException(400, "このインタビューは保存済みです")
        if not s["draft"]:
            raise HTTPException(400, "まだまとめを作っていません")
        _limit(c, s["ip_hash"], "save")
        d = json.loads(s["draft"])
        d["summary"] = summary
        ok, why = True, ""
        if v.want_public:
            whole = "\n".join([summary, *d.get("reasons", []), d.get("impact", ""), d.get("concerns", ""), d.get("proposals", "")])
            ok, why = interview.moderate(whole)
        rid, key = secrets.token_hex(5), secrets.token_urlsafe(12)
        public = 1 if (v.want_public and ok) else 0
        with c:
            c.execute("""INSERT INTO report (id, session_id, bill_id, stance, summary, reasons, impact, concerns, proposals,
                         want_public, moderation, moderation_reason, public, view_key, is_test, model, created_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                      (rid, sid, s["bill_id"], d["stance"], summary, json.dumps(d.get("reasons", []), ensure_ascii=False),
                       d.get("impact", ""), d.get("concerns", ""), d.get("proposals", ""), int(v.want_public),
                       ("ok" if ok else "hidden") if v.want_public else "private", why, public, key, s["is_test"], llm.MODEL))
            c.execute("UPDATE session SET state='saved', updated_at=datetime('now','localtime') WHERE id=?", (sid,))
        url = f"{BASE}/r/{rid}" + ("" if public else f"?k={key}")
        if public:
            msg = "公開しました。法案ページの「みんなの意見」に出ます。話題への振り分けは定期処理で行います。"
        elif v.want_public:
            msg = f"保存しましたが、公開の判定で止まったため公開していません（{why}）。下のリンクはあなたにだけ見えます。"
        else:
            msg = "公開せずに保存しました。下のリンクはあなたにだけ見えます（なくすと見られなくなります）。"
        return {"report_id": rid, "public": bool(public), "report_url": url, "message": msg}
    finally:
        c.close()


# ── API（条文への修正提案） ─────────────────────────────

class Ask(BaseModel):
    bill_id: str
    q: str


@app.post("/api/ask")
def ask_bill(v: Ask, req: Request):
    """法案について質問する。材料はその法案の要約・条文・国会の質疑と答弁だけ（app/ask.py）"""
    q = " ".join(v.q.split())
    if not q or len(q) > ask.MAX_Q:
        raise HTTPException(400, f"質問は1〜{ask.MAX_Q}字で書いてください")
    c = connect()
    try:
        b = _bill(c, v.bill_id)
        _limit(c, _hash(_ip(req)), "ask")
        arts = [dict(r) for r in c.execute("SELECT * FROM article WHERE bill_id=? ORDER BY ord", (b["id"],))]
        sp = [dict(r) for r in c.execute("SELECT * FROM bill_speech WHERE bill_id=? ORDER BY date DESC, speech_id DESC", (b["id"],))]
    finally:
        c.close()
    try:
        return ask.answer(b, q, ask.sources(b, arts, sp, BASE))
    except llm.LLMError:
        raise HTTPException(503, "AIが混み合っています。時間をおいてからもう一度お試しください。")


class AmendDraft(BaseModel):
    bill_id: str
    ord: int
    request: str


class AmendSave(BaseModel):
    bill_id: str
    ord: int
    kind: str
    before: str = ""
    after: str = ""
    proposal: str
    reason: str = ""
    want_public: bool
    consent: bool


def _amend_target(c, bid: str, ord_: int) -> tuple[dict, dict]:
    b = _bill(c, bid)
    if b["status"] not in ACTIVE:
        raise HTTPException(400, "この法案の審議は終わっています")
    return b, _article(c, bid, ord_)


@app.post("/api/amend/draft")
def amend_draft(v: AmendDraft, req: Request):
    text = " ".join(v.request.split())
    if not text or len(text) > 400:
        raise HTTPException(400, "要望は1〜400字で書いてください")
    c = connect()
    try:
        b, a = _amend_target(c, v.bill_id, v.ord)
        _limit(c, _hash(_ip(req)), "amend_draft")
    finally:
        c.close()
    try:
        return amend.draft(b, a, text)
    except llm.LLMError:
        raise HTTPException(503, "AIが混み合っています。時間をおいてからもう一度お試しください。")


@app.post("/api/amend/save")
def amend_save(v: AmendSave, req: Request):
    if not v.consent:
        raise HTTPException(400, "保存への同意が必要です")
    proposal = " ".join(v.proposal.split())
    reason = " ".join(v.reason.split())
    if not proposal or len(proposal) > 600:
        raise HTTPException(400, "提案は1〜600字で書いてください")
    if len(reason) > 600:
        raise HTTPException(400, "理由は600字までです")
    kind = v.kind if v.kind in amend.KINDS else "その他"
    before, after = " ".join(v.before.split())[:80], " ".join(v.after.split())[:150]
    c = connect()
    try:
        b, a = _amend_target(c, v.bill_id, v.ord)
        if before and not amend.in_text(before, a["text"]):
            raise HTTPException(400, "「直す前の語句」が条文に見つかりません。条文からそのまま写してください。")
        iph = _hash(_ip(req))
        _limit(c, iph, "amend_save")
        ok, why = True, ""
        if v.want_public:
            ok, why = interview.moderate("\n".join([proposal, reason, after]))
        mid, key = secrets.token_hex(5), secrets.token_urlsafe(12)
        public = 1 if (v.want_public and ok) else 0
        with c:
            c.execute("""INSERT INTO amendment (id, bill_id, ord, kind, before, after, proposal, reason, want_public,
                         moderation, moderation_reason, public, view_key, ip_hash, is_test, model, created_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,datetime('now','localtime'))""",
                      (mid, v.bill_id, v.ord, kind, before, after, proposal, reason, int(v.want_public),
                       ("ok" if ok else "hidden") if v.want_public else "private", why, public, key, iph, llm.MODEL))
        url = f"{BASE}/m/{mid}" + ("" if public else f"?k={key}")
        if public:
            msg = "公開しました。この条のページの「出された修正提案」に出ます。"
        elif v.want_public:
            msg = f"保存しましたが、公開の判定で止まったため公開していません（{why}）。下のリンクはあなたにだけ見えます。"
        else:
            msg = "公開せずに保存しました。下のリンクはあなたにだけ見えます（なくすと見られなくなります）。"
        return {"amendment_id": mid, "public": bool(public), "url": url, "message": msg}
    finally:
        c.close()


@app.exception_handler(HTTPException)
def _http_err(req: Request, e: HTTPException):
    if req.url.path.startswith("/api/"):
        return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return HTMLResponse(pages.page("見つかりません", "", req.url.path,
                                   f'<h1>{pages.h(e.detail)}</h1><p><a href="{BASE}/">法案の一覧へ</a></p>', noindex=True),
                        status_code=e.status_code)
