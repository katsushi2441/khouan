#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法律案の本文を条ごとに取り込む（条文への修正提案のため・2026-10-15）。

  .venv/bin/python -m scripts.import_articles            # 審議中の法案すべて（取り込み済みは飛ばす）
  .venv/bin/python -m scripts.import_articles --bill 221-shu-19 --force

- 出典は衆議院の「議案本文情報」の提出時法律案（HTML）。URL は g＋会期3けた＋種類2けた＋番号3けた
  （05＝衆法・06＝参法・09＝閣法。2026-10-15 に一覧ページの並びで確かめた）。
- 参議院だけに出ている法案（参法で衆議院に送られていないもの）は本文が縦書きのPDFしかなく、
  句読点やかっこが□に化けるので取り込まない（画面で PDF を案内する）。
- 条の切り方: 行頭の「第◯条　」（全角空白つき）で切る。改正する法律案の中に出てくる「第五条の二　…」のような
  差し込まれる条の文は、条の番号が順番どおりでなければ前の条の続きとして扱う（取り違えて別の条にしない）。
  附則に入ったら番号を数え直し、「附則第一条」のように呼ぶ。条が無い附則は「附則」1つにまとめる。
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.store import connect, init_db  # noqa: E402

UA = "khouan/1.0 (+https://kurage.exbridge.jp/khouan.php/)"
KIND = {"shu": "05", "san": "06", "kaku": "09"}
NUM = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
ART = re.compile(r"^第([一二三四五六七八九十百〇]+)条(?:の([一二三四五六七八九十]+))?[　 ]")


def kan(s: str) -> int:
    """漢数字（十・百を含む）を数に"""
    if not s:
        return 0
    if "百" in s:
        a, b = s.split("百", 1)
        return (kan(a) or 1) * 100 + kan(b)
    if "十" in s:
        a, b = s.split("十", 1)
        return (kan(a) or 1) * 10 + kan(b)
    n = 0
    for ch in s:
        n = n * 10 + NUM.get(ch, 0)
    return n


def source_url(bid: str) -> str | None:
    m = re.match(r"^(\d+)-(shu|san|kaku)-(\d+)$", bid)
    if not m:
        return None
    s, k, n = m.groups()
    return (f"https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/"
            f"g{int(s):03d}{KIND[k]}{int(n):03d}.htm")


def fetch_lines(url: str) -> list[str] | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, timeout=60).read()
    except Exception:  # noqa: BLE001
        return None
    h = raw.decode("shift_jis", "ignore")
    if "エントリが索引に見つかりません" in h or "第一条" not in h and "附　則" not in h:
        return None
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", h)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t).replace("&nbsp;", " ").replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    lines = [ln.rstrip() for ln in t.splitlines()]
    # 本文は「第ニニ一回」「衆第一九号」のあとの法案名から。目次・本則・附則まで
    start = next((i for i, ln in enumerate(lines) if re.match(r"^\s*(衆|参|閣)?第[〇一二三四五六七八九十]+号\s*$", ln.strip())), None)
    if start is None:
        return None
    end = next((i for i in range(start, len(lines)) if lines[i].strip() in ("ホームページについて", "理　由", "理由")), len(lines))
    body = [ln for ln in lines[start + 1:end] if ln.strip()]
    return body


HEAD = re.compile(r"^（[^）]{1,30}）$")
CHAP = re.compile(r"^第[一二三四五六七八九十]+[章節款]　")
SUPP = re.compile(r"^附　?則(\s|$)")


def split_articles(lines: list[str]) -> list[dict]:
    """lines は「衆第◯号」の次の行から。先頭は法案名"""
    lines = [ln.strip() for ln in lines]
    if not lines:
        return []
    i0 = 1                                   # 法案名の次から
    if i0 < len(lines) and lines[i0] == "目次":
        # 目次を飛ばす：目次の項目は「（第一条−第六条）」や章の名前・附則。最初の見出し（（目的）など）か条の行の手前まで飛ばし、
        # そのすぐ上にある本文の章の行は残す
        j = next((k for k in range(i0 + 1, len(lines)) if HEAD.match(lines[k]) or ART.match(lines[k])), len(lines))
        while j > i0 + 1 and CHAP.match(lines[j - 1]) and "（第" not in lines[j - 1]:
            j -= 1
        i0 = j
    out, cur, chapter, supp, expect, pending = [], None, "", False, 1, ""

    def in_amend() -> bool:   # 改正の文の中か（中に出てくる章・見出し・条は、書き換え後の本文の一部）
        return bool(cur) and "改正する。" in "\n".join(cur["lines"])

    for s in lines[i0:]:
        if SUPP.match(s):
            if cur and cur["lines"]:
                out.append(cur)
            cur, supp, expect, pending = {"label": "附則", "heading": "", "chapter": "附則", "lines": []}, True, 1, ""
            continue
        if CHAP.match(s) and not in_amend():
            chapter = s
            continue
        if HEAD.match(s):
            if pending and cur:
                cur["lines"].append(pending)
            pending = s
            continue
        m = ART.match(s)
        main_art = bool(m) and not m.group(2) and kan(m.group(1)) == expect
        if main_art and in_amend() and not supp:
            # 改正の文の中の「第◯条　…」（書き換え後の条文）では切らない。次の法律を改正する条（…を次のように改正する。）だけ切る
            main_art = "改正する。" in s and cur["label"] != "本則"
        if main_art:
            if cur and (cur["lines"] or cur["label"] != "附則"):
                out.append(cur)
            label = ("附則" if supp else "") + f"第{m.group(1)}条"
            cur = {"label": label, "heading": pending, "chapter": "附則" if supp else chapter, "lines": [s]}
            pending, expect = "", expect + 1
            continue
        if cur is None:
            # 条の番号が無い本則（一部を改正する法律案で、改正する法律が1つのとき）
            cur = {"label": "本則", "heading": "（改正の文）" if "改正する。" in s else "", "chapter": "", "lines": []}
        if pending:
            cur["lines"].append(pending)
            pending = ""
        cur["lines"].append(s)
    if cur and cur["lines"]:
        out.append(cur)
    return [{"label": a["label"], "heading": a["heading"], "chapter": a["chapter"], "text": "\n".join(a["lines"])} for a in out]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bill")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    init_db()
    c = connect()
    bills = [r["id"] for r in c.execute("SELECT id FROM bill WHERE status IN ('委員会で審査中','審議中') ORDER BY id")]
    if a.bill:
        bills = [a.bill]
    for bid in bills:
        have = c.execute("SELECT COUNT(*) FROM article WHERE bill_id=?", (bid,)).fetchone()[0]
        if have and not a.force:
            continue
        url = source_url(bid)
        lines = fetch_lines(url) if url else None
        time.sleep(1)
        if not lines:
            print(f"  {bid}: 衆議院の本文HTMLが無い（参議院のPDFだけ）")
            continue
        arts = split_articles(lines)
        with c:
            c.execute("DELETE FROM article WHERE bill_id=?", (bid,))
            for i, x in enumerate(arts, 1):
                c.execute("INSERT INTO article (bill_id, ord, label, heading, chapter, text, source_url, imported_at) "
                          "VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))",
                          (bid, i, x["label"], x["heading"], x["chapter"], x["text"], url))
        print(f"  {bid}: {len(arts)}条 " + "・".join(x["label"] for x in arts[:6]) + ("…" if len(arts) > 6 else ""))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
