"""SQLite の置き場。

- bill / bill_speech は xb4g/giin の giin.sqlite から写したもの（scripts/import_bills.py）。要約・数字・日付は giin のものをそのまま使う。
- question は法案ごとの聞く項目（gemma4 で作って保存。毎回作り直さない）。
- session / message はインタビューのやりとり。氏名は聞かない。IP はそのまま持たず、塩つきハッシュだけ（回数の上限に使う）。
- report は本人が確認・同意して保存した「意見のまとめ」。公開は本人が選び、さらに荒らし・個人情報の判定を通ったものだけ。
- topic / topic_member は公開に同意されたレポートを話題に束ねた結果（scripts/build_topics.py）。
- article は法律案の本文を条ごとに、amendment はその条への修正提案（2026-10-15〜）。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("KHOUAN_DB", str(ROOT / "data" / "khouan.sqlite")))

DDL = """
CREATE TABLE IF NOT EXISTS bill (
  id TEXT PRIMARY KEY, session INTEGER, title TEXT, law_name TEXT, kind TEXT, kind_code TEXT,
  submitter TEXT, submitted TEXT, status TEXT, last_date TEXT, sessions TEXT,
  shu_committee TEXT, san_committee TEXT,
  url TEXT, summary_url TEXT, text_url TEXT,
  explain TEXT,            -- giin の「この法案で変わること」（JSON 配列。数字・日付は giin で照合済み）
  explain_source TEXT,     -- 要旨 / 理由
  answer TEXT,             -- 状態の一文（giin の g_bill_answer と同じ組み立て）
  timeline TEXT,           -- 審議の経過（JSON [[日付, できごと], ...]）
  imported_at TEXT
);
CREATE TABLE IF NOT EXISTS bill_speech (
  bill_id TEXT, speech_id TEXT, date TEXT, house TEXT, meeting TEXT, speaker TEXT, position TEXT,
  role TEXT, url TEXT, excerpt TEXT, PRIMARY KEY (bill_id, speech_id)
);
CREATE TABLE IF NOT EXISTS question (
  bill_id TEXT, ord INTEGER, kind TEXT, text TEXT, model TEXT, created_at TEXT,
  PRIMARY KEY (bill_id, ord)
);
CREATE TABLE IF NOT EXISTS session (
  id TEXT PRIMARY KEY, bill_id TEXT, ip_hash TEXT, state TEXT,   -- asking / done / saved
  q_index INTEGER DEFAULT 0, followups INTEGER DEFAULT 0, turns INTEGER DEFAULT 0,
  draft TEXT, is_test INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS message (
  id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, qord INTEGER, kind TEXT, text TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS report (
  id TEXT PRIMARY KEY, session_id TEXT, bill_id TEXT,
  stance TEXT, summary TEXT, reasons TEXT, impact TEXT, concerns TEXT, proposals TEXT,
  want_public INTEGER,            -- 本人が「公開してよい」を選んだか
  moderation TEXT,                -- ok / hidden
  moderation_reason TEXT,
  public INTEGER,                 -- want_public かつ moderation=ok
  view_key TEXT,                  -- 本人が非公開のレポートを見るための鍵（URL の ?k=）
  is_test INTEGER DEFAULT 0, model TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS topic (
  id INTEGER PRIMARY KEY, bill_id TEXT, ord INTEGER, name TEXT, summary TEXT, propositions TEXT,
  size INTEGER, is_test INTEGER DEFAULT 0, built_at TEXT
);
CREATE TABLE IF NOT EXISTS topic_member (
  topic_id INTEGER, report_id TEXT, rank INTEGER, PRIMARY KEY (topic_id, report_id)
);
CREATE TABLE IF NOT EXISTS handoff (
  bill_id TEXT PRIMARY KEY, kconsensus_slug TEXT, statements INTEGER, reactions INTEGER, at TEXT
);
CREATE TABLE IF NOT EXISTS article (     -- 法律案の本文を条ごとに（scripts/import_articles.py・衆議院の議案本文情報）
  bill_id TEXT, ord INTEGER, label TEXT, heading TEXT, chapter TEXT, text TEXT, source_url TEXT, imported_at TEXT,
  PRIMARY KEY (bill_id, ord)
);
CREATE TABLE IF NOT EXISTS amendment (   -- 条文への修正提案。本人が同意して保存したものだけ。公開は本人が選び、判定を通ったものだけ
  id TEXT PRIMARY KEY, bill_id TEXT, ord INTEGER,
  kind TEXT,                      -- 改める / 削る / 加える / その他
  before TEXT, after TEXT,        -- 「A」を「B」に（AI で整えたとき。A は条文に実際にある語句だけ）
  proposal TEXT, reason TEXT,
  want_public INTEGER, moderation TEXT, moderation_reason TEXT, public INTEGER, view_key TEXT,
  ip_hash TEXT, is_test INTEGER DEFAULT 0, model TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS hit (
  ip_hash TEXT, kind TEXT, at REAL
);
CREATE INDEX IF NOT EXISTS msg_session ON message(session_id);
CREATE INDEX IF NOT EXISTS report_bill ON report(bill_id);
CREATE INDEX IF NOT EXISTS topic_bill ON topic(bill_id);
CREATE INDEX IF NOT EXISTS hit_ip ON hit(ip_hash, kind, at);
CREATE INDEX IF NOT EXISTS amend_bill ON amendment(bill_id, ord);
"""


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    c = connect()
    with c:
        c.executescript(DDL)
    c.close()
