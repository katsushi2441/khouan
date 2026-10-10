"""AIインタビューの中身（聞く項目・深掘り・意見のまとめ・荒らしと個人情報の判定）。

AI がするのは、聞くこと・言い換えること・まとめることだけ。利用者の意見に足したり、
どちらかの立場に誘導したりしない。法案の説明は giin の要約（数字・日付は照合済み）だけを材料にする。
"""
from __future__ import annotations

import json
import re

from . import llm

KINDS = ["賛否", "理由", "影響", "懸念", "提案"]

# 作れなかったときの聞き方（法案名だけを差し込む。内容は足さない）
FALLBACK = [
    ("賛否", "{name}に、あなたは賛成ですか、反対ですか。まだ決めていない・分からない、でもかまいません。"),
    ("理由", "そう考える理由を教えてください。"),
    ("影響", "この法案が通ったら、あなたの暮らしや仕事、身の回りにどんな影響がありそうですか。"),
    ("懸念", "この法案について、心配なことや、はっきりさせてほしい点はありますか。"),
    ("提案", "国会での審議や法案の中身について、こうしてほしいという提案があれば教えてください。"),
]


def bill_brief(b: dict) -> str:
    ex = json.loads(b.get("explain") or "[]")
    lines = "\n".join(f"- {x}" for x in ex)
    return f"法案名: {b['title']}\n状態: {b.get('answer') or ''}\nこの法案で変わること（要約）:\n{lines}"


Q_SCHEMA = {"type": "object", "properties": {"questions": {"type": "array", "items": {
    "type": "object", "properties": {"kind": {"type": "string", "enum": KINDS}, "text": {"type": "string"}},
    "required": ["kind", "text"]}}}, "required": ["questions"]}

Q_PROMPT = """あなたは、国会で審議中の法案について、市民の意見を聞くインタビューの設問を作る担当です。
次の法案の説明だけを材料に、市民に聞く質問を5問、日本語で作ってください。

{brief}

決まり:
- 順番と種類は、1問目「賛否」（賛成か反対か、まだ決めていないか）、2問目「理由」、3問目「影響」（自分の暮らしや仕事への影響）、4問目「懸念」、5問目「提案」。
- 1問は60字以内。中学生にも分かる言葉で、1問で1つのことだけを聞く。
- 法案の中身にふれるときは、上の説明に書いてあることだけを使う。数字や日付、説明に無い事実を足さない。
- どちらかの立場に誘導しない（「〜は問題だと思いませんか」のような聞き方をしない）。
- 1問目は「まだ決めていない・分からない、でもかまいません」と添える。
"""


def make_questions(b: dict) -> list[tuple[str, str]]:
    """法案ごとの聞く項目（4〜6問）。作れなかったら FALLBACK。"""
    name = b["law_name"] or b["title"]
    try:
        d = llm.ask_json(Q_PROMPT.format(brief=bill_brief(b)), Q_SCHEMA, temperature=0.1, timeout=300)
        qs = [(llm.text(q.get("kind")), llm.text(q.get("text"))) for q in (d.get("questions") or [])
              if isinstance(q, dict)]
        qs = [(k if k in KINDS else "その他", t[:120]) for k, t in qs if t]
    except llm.LLMError:
        qs = []
    if not (4 <= len(qs) <= 6) or qs[0][0] != "賛否":
        return [(k, t.format(name=name)) for k, t in FALLBACK]
    return qs


F_SCHEMA = {"type": "object", "properties": {
    "ask": {"type": "boolean"}, "question": {"type": "string"}}, "required": ["ask", "question"]}

F_PROMPT = """あなたは、国会で審議中の法案について市民の意見を聞くインタビュアーです。

{brief}

いまの質問: {q}
相手の答え: {a}

相手の答えをもう少し具体的に聞くと、意見がはっきりする場合だけ、追加の質問を1つ作ってください。
- 答えがすでに具体的なとき、「分からない」「特にない」などで答えたくなさそうなとき、答えが質問と関係ないときは ask を false にします。
- 追加の質問は50字以内。相手の言葉を受けて、理由・具体的な場面・どうしてほしいか のどれか1つを聞きます。
- 相手の意見を評価したり、反論したり、別の立場に誘導したりしません。法案の説明に無い事実を足しません。
ask が false のときは question を空にします。
"""


def follow_up(b: dict, q: str, a: str) -> str:
    if len(a) < 4 or (len(a) < 20 and re.search(r"(特に|とくに)?(ない|なし|ありません|わからない|分からない|わかりません|分かりません|スキップ)[。！!]*$", a)):
        return ""
    try:
        d = llm.ask_json(F_PROMPT.format(brief=bill_brief(b), q=q, a=a), F_SCHEMA, temperature=0.2,
                         num_predict=200, timeout=90)
    except llm.LLMError:
        return ""
    t = llm.text(d.get("question"))
    return t[:100] if d.get("ask") is True and t else ""


R_SCHEMA = {"type": "object", "properties": {
    "stance": {"type": "string", "enum": ["賛成", "どちらかといえば賛成", "どちらとも言えない", "どちらかといえば反対", "反対", "分からない"]},
    "summary": {"type": "string"},
    "reasons": {"type": "array", "items": {"type": "string"}},
    "impact": {"type": "string"}, "concerns": {"type": "string"}, "proposals": {"type": "string"}},
    "required": ["stance", "summary", "reasons", "impact", "concerns", "proposals"]}

R_PROMPT = """あなたは、市民へのインタビューの記録から「意見のまとめ」を作る担当です。

{brief}

インタビューの記録:
{log}

この人の意見を、この人の言葉に沿ってまとめてください。
- stance は、1問目などの答えから読み取れる立場。本人の言い方にいちばん近いものを選ぶ（「どちらかといえば賛成」と答えたら「どちらかといえば賛成」）。はっきりしなければ「どちらとも言えない」か「分からない」。
- summary は、この人の意見の要点を120字以内で。「〜という意見。」のような書き方にし、主語は書かない。
- reasons は、そう考える理由を1〜3個（各40字以内）。答えに無ければ空の配列。
- impact は、本人が挙げた自分への影響（60字以内）。無い・「特にない」なら空文字。
- concerns は、懸念（60字以内）。無ければ空文字。
- proposals は、提案（60字以内）。無ければ空文字。
- 答えに書かれていないことを足さない。あなたの意見を混ぜない。氏名・住所・電話番号・勤務先名などの個人を特定できる情報は書かない。
"""


def make_report(b: dict, log: list[tuple[str, str]]) -> dict:
    lg = "\n".join(f"{'質問' if r == 'ai' else '答え'}: {t}" for r, t in log)
    d = llm.ask_json(R_PROMPT.format(brief=bill_brief(b), log=lg), R_SCHEMA, temperature=0.1, timeout=150)
    reasons = d.get("reasons") or []
    reasons = [llm.text(x)[:80] for x in (reasons if isinstance(reasons, list) else [reasons]) if llm.text(x)][:3]
    return {"stance": llm.text(d.get("stance")) or "分からない", "summary": llm.text(d.get("summary"))[:240],
            "reasons": reasons, "impact": llm.text(d.get("impact"))[:120],
            "concerns": llm.text(d.get("concerns"))[:120], "proposals": llm.text(d.get("proposals"))[:120]}


# 個人情報は、まず決まった形（電話・メール・郵便番号・URL）で見る。AI の判定より先に、確実に止める
PII = [
    (re.compile(r"0\d{1,4}[-ー‐ 　]?\d{1,4}[-ー‐ 　]?\d{3,4}"), "電話番号らしい数字"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "メールアドレス"),
    (re.compile(r"〒?\d{3}[-ー‐]\d{4}"), "郵便番号"),
    (re.compile(r"https?://|www\.", re.I), "URL"),
]

M_SCHEMA = {"type": "object", "properties": {
    "abusive": {"type": "boolean"}, "personal_info": {"type": "boolean"}, "spam": {"type": "boolean"},
    "reason": {"type": "string"}}, "required": ["abusive", "personal_info", "spam", "reason"]}

M_PROMPT = """次の文は、法案についての市民の意見です。公開してよいかを判定してください。

{text}

- abusive: 特定の人や集団への悪口・侮辱・差別・脅し・下品な言葉がはっきり含まれていれば true。法案や政策への強い批判・反対は悪口ではないので false。
- personal_info: 実在の個人を特定できる情報（本人や他人の氏名、住所、電話番号、メール、勤務先や学校の名前など）が含まれていれば true。政治家の名前や、自分の職業・立場（「介護職です」など）は false。
- spam: 宣伝・意味のない文字の並び・法案と無関係な内容なら true。
- reason: 判定の理由を30字以内で。
"""


def moderate(text: str) -> tuple[bool, str]:
    """公開してよければ (True, '')。止めるなら (False, 理由)。判定できなかったときも止める（公開しない側に倒す）。"""
    for rx, why in PII:
        if rx.search(text):
            return False, why
    try:
        d = llm.ask_json(M_PROMPT.format(text=text[:2000]), M_SCHEMA, temperature=0, num_predict=120, timeout=90)
    except llm.LLMError:
        return False, "判定できなかったため"
    flags = [k for k in ("abusive", "personal_info", "spam") if d.get(k) is True]
    if flags:
        name = {"abusive": "悪口・侮辱", "personal_info": "個人情報", "spam": "宣伝・無関係"}
        return False, "・".join(name[k] for k in flags) + "（" + llm.text(d.get("reason"))[:40] + "）"
    return True, ""
