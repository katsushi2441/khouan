"""法案について質問する（2026-10-16〜）。

市民が法案について質問し、AI がその法案の公的な記録だけを材料に答える。
Jigsaw「Facilitation in the AI Era」（2025-10）の Dynamic Learning ——「形式は人ごとに変えても、
全員が同じ情報を受け取れるようにする」—— を、法案ページで受け持つ。インタビュー（AI が聞く）の前に、
市民が中身を理解する段（ORID の「事実」）にあたる。

決めごと:
- 材料は、その法案の要約（giin で数字・日付を照合済み）・条文（衆議院の議案本文）・国会の質疑と答弁だけ。
- AI には材料に番号（S1, S2, …）を付けて渡し、答えの中で番号を示させる。材料に無いことは「記録に無い」と返させる。
- 出す前にプログラムで検査する：「」の中は材料にそのままある文か／数字は示した材料にあるか／番号は渡したものか。
  外れたら AI の文は出さず、関係しそうな材料だけを並べる（質問主意書アシストの下書きと同じ考え方）。
- 賛否や意見は言わせない。
"""
from __future__ import annotations

import json
import re

from . import llm

MAX_Q = 200
MAX_SRC = 7
MAX_CHARS = 7000


def _norm(s: str) -> str:
    return re.sub(r"[\s　]+", "", s or "")


def _grams(s: str) -> set[str]:
    t = _norm(s)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def sources(bill: dict, arts: list[dict], speeches: list[dict], base: str) -> list[dict]:
    """その法案の材料を、同じ形の辞書にそろえる"""
    out = []
    ex = json.loads(bill.get("explain") or "[]")
    if ex:
        out.append({"kind": "要約", "label": "この法案で変わること（要約）", "text": "\n".join(ex),
                    "url": f"{base}/b/{bill['id']}/"})
    for a in arts:
        out.append({"kind": "条文", "label": f"{a['label']}{a.get('heading') or ''}", "text": a["text"],
                    "url": f"{base}/b/{bill['id']}/a/{a['ord']}"})
    for s in speeches:
        who = s["speaker"] + (f"（{s['position']}）" if s.get("position") else "")
        out.append({"kind": "答弁" if s.get("role") == "gov" else "質疑",
                    "label": f"{s['date']} {s['house']} {s['meeting']}・{who}", "text": s.get("excerpt") or "",
                    "url": s.get("url") or ""})
    return [x for x in out if x["text"].strip()]


# 市民のことばを、法令の言い方に広げる（「自治体」で聞かれても条文は「地方公共団体」。2026-10-16 の試験で第四条・第五条を拾えなかった）
SYN = [
    (r"自治体|市町村|都道府県|県|市", "地方公共団体"),
    (r"国(?!会|民)|政府", "国の責務 政府"),   # 「国」は1字で、字の重なり（2字ずつ）では数えられない
    (r"義務|やらなければ|しなければ|役割", "責務"),   # 「ものとする」等はほぼ全部の条にあり、長い条ほど点が上がるので入れない
    (r"会社|企業|業者|お店|店", "事業者"),
    (r"いつから|いつ|開始|始まる|始まり", "施行 公布の日"),
    (r"罰|罰則|違反|捕まる", "罰則 罰金 懲役 拘禁刑"),
    (r"対象|だれ|誰|どんな人", "定義 この法律において"),
    (r"目的|なぜ|何のため", "目的"),
    (r"お金|予算|財源|費用|税金", "財政上の措置 予算"),
]


def expand(question: str) -> str:
    extra = [w for pat, w in SYN if re.search(pat, question)]
    return question + " " + " ".join(extra)


def pick(question: str, srcs: list[dict]) -> list[dict]:
    """質問と字の重なりが多い材料から。条の見出しに当たったものは重く数える。要約は必ず入れる（全体の説明の土台）"""
    q = _grams(expand(question))
    scored = []
    for i, s in enumerate(srcs):
        g = _grams(s["label"] + s["text"][:1500])
        sc = len(q & g) / (len(q) or 1) + 2 * len(q & _grams(s["label"])) / (len(q) or 1)
        if s["kind"] == "要約":
            sc += 1.0
        scored.append((sc, i))
    scored.sort(reverse=True)
    out, total = [], 0
    for sc, i in scored:
        s = srcs[i]
        t = s["text"][:1800]
        if len(out) >= MAX_SRC:
            break
        if total + len(t) > MAX_CHARS:
            continue   # 大きい材料で打ち切らず、後ろの短い条（第四条（国の責務）など）は入れる
        out.append({**s, "text": t})
        total += len(t)
    return out


SCHEMA = {"type": "object", "properties": {
    "found": {"type": "boolean"},
    "answer": {"type": "string"},
    "used": {"type": "array", "items": {"type": "string"}}},
    "required": ["found", "answer", "used"]}

PROMPT = """あなたは、国会で審議中の法律案について、市民の質問に答える案内係です。
下の「材料」だけを根拠に、質問に日本語で答えてください。

決まり:
- 材料に書いてあることだけを答える。材料に無いことは推測せず、found を false にして「この法案の記録には書かれていません」と答える。
- 答えの文の後ろに、根拠にした材料の番号を [S1] のように付ける。used に使った番号を全部入れる。
- 材料の文をそのまま引くときは「」に入れ、一字一句変えない。数字や日付は材料にあるものだけを使う。
- 法案への賛成・反対、よしあし、あなたの意見は書かない。
- 中学生にも分かる言葉で、250字以内。

# 法律案
{title}

# 材料
{src}

# 質問
{q}
"""


def _check(ans: str, used: list[str], picked: dict[str, dict]) -> str:
    """出してよい答えか。だめなら理由を返す（空ならよい）"""
    if not ans:
        return "空"
    ids = set(re.findall(r"S\d+", " ".join(used) + " " + ans))
    if not ids:
        return "根拠の番号が無い"
    if any(i not in picked for i in ids):
        return "渡していない番号"
    hay = _norm("".join(picked[i]["text"] + picked[i]["label"] for i in ids))
    for qt in re.findall(r"「([^」]{4,})」", ans):
        if _norm(qt) not in hay:
            return f"引用が材料に無い: {qt[:20]}"
    body = re.sub(r"\[S\d+\]|S\d+", "", ans)
    for num in set(re.findall(r"\d[\d,，.]*\d|\d", body)):
        n = num.replace("，", ",")
        if n not in hay and n.replace(",", "") not in hay:
            return f"数字が材料に無い: {num}"
    return ""


def answer(bill: dict, question: str, srcs: list[dict]) -> dict:
    sel = pick(question, srcs)
    picked = {f"S{i}": s for i, s in enumerate(sel, 1)}
    src_txt = "\n\n".join(f"[{k}] {s['kind']}｜{s['label']}\n{s['text']}" for k, s in picked.items())
    d = llm.ask_json(PROMPT.format(title=bill["title"], src=src_txt, q=question), SCHEMA,
                     temperature=0.1, num_predict=700, timeout=150)
    ans = llm.text(d.get("answer"))[:600]
    used = [llm.text(x) for x in (d.get("used") or []) if isinstance(x, (str, dict))]
    found = d.get("found") is True
    why = _check(ans, used, picked) if found else ""
    cited = sorted(set(re.findall(r"S\d+", " ".join(used) + " " + ans)) & set(picked), key=lambda x: int(x[1:]))
    refs = [{"id": k, "kind": picked[k]["kind"], "label": picked[k]["label"], "url": picked[k]["url"],
             "excerpt": picked[k]["text"][:160]} for k in cited]
    related = [{"id": k, "kind": s["kind"], "label": s["label"], "url": s["url"], "excerpt": s["text"][:160]}
               for k, s in list(picked.items())[:4]]
    if not found:
        return {"ok": True, "found": False, "answer": "この法案の記録（要約・条文・国会の質疑と答弁）には、答えが書かれていませんでした。関係しそうな記録を並べます。",
                "refs": related}
    if why:
        return {"ok": True, "found": False, "checked": False,
                "answer": "AIの答えが記録と照らし合わせて確かめられなかったので、出していません。関係しそうな記録を並べます。",
                "refs": related, "why": why}
    return {"ok": True, "found": True, "checked": True, "answer": ans, "refs": refs}
