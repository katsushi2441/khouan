"""条文への修正提案（2026-10-15〜）。

いどばた政策（政策案の文への改善提案）にあたる機能を、国会で審議中の法案の条文に対して持つ。
- 提案は人が書く。AI（gemma4）は「どの語句を、どう直すか」を条文の形に整える手伝いだけをする。
- AI が出した「直す前の語句」は、条文に実際にあるときだけ使う（無ければ形にしない）。
- 修正の文（「第三条中「A」を「B」に改める。」）は AI に書かせず、ここで組み立てる（法令の書き方の形を崩さない）。
"""
from __future__ import annotations

import re

from . import llm

KINDS = ["改める", "削る", "加える", "その他"]


def _norm(s: str) -> str:
    return re.sub(r"[\s　]+", "", s or "")


def in_text(phrase: str, text: str) -> bool:
    p = _norm(phrase)
    return bool(p) and p in _norm(text)


def sentence(label: str, kind: str, before: str, after: str) -> str:
    """修正の文。本則（番号の無い改正の文）は「本則中」"""
    where = "本則中" if label == "本則" else f"{label}中"
    if kind == "改める" and before and after:
        return f"{where}「{before}」を「{after}」に改める。"
    if kind == "削る" and before:
        return f"{where}「{before}」を削る。"
    if kind == "加える" and after:
        return f"{label}に、次の趣旨の規定を加える。「{after}」"
    return ""


def draft(bill: dict, art: dict, request: str) -> dict:
    """要望（自由な文）→ {kind, before, after, sentence, note}。before は条文にある語句だけ"""
    schema = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "before": {"type": "string"}, "after": {"type": "string"}, "note": {"type": "string"}},
        "required": ["kind", "before", "after", "note"]}
    prompt = (
        "あなたは法律案の修正提案を手伝う人です。次の条文に対する市民の要望を、修正の形に整えてください。\n"
        "- kind：改める（語句を別の語句に）／削る（語句を消す）／加える（新しい規定を足す）／その他（形にできない）\n"
        "- before：直す前の語句。**条文の中に一字一句そのままある語句だけ**を、できるだけ短く（80字以内）。加える・その他は空\n"
        "- after：直した後の語句、または加える規定の文（150字以内）。削る・その他は空でよい\n"
        "- note：要望の趣旨を、ふつうの言葉で1文（60字以内）\n"
        "要望に書かれていないことを足さない。条文の書き方（〜するものとする、など）に合わせる。\n\n"
        f"# 法律案\n{bill['title']}\n\n# 条文（{art['label']}{art.get('heading') or ''}）\n{art['text'][:2500]}\n\n"
        f"# 市民の要望\n{request}\n")
    d = llm.ask_json(prompt, schema, temperature=0.1, num_predict=500)
    kind = d.get("kind") if d.get("kind") in KINDS else "その他"
    before = llm.text(d.get("before"))[:80]
    after = llm.text(d.get("after"))[:150]
    note = llm.text(d.get("note"))[:80]
    checked = True
    if kind in ("改める", "削る") and not in_text(before, art["text"]):
        before, checked = "", False
        kind = "その他" if kind == "削る" else kind
    s = sentence(art["label"], kind, before, after)
    return {"kind": kind, "before": before, "after": after, "sentence": s, "note": note,
            "checked": checked,
            "warning": "" if checked else "AIが示した「直す前の語句」が条文に見つからなかったので、修正の形にしていません。直したい語句を条文からそのまま写して書き直してください。"}
