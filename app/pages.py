"""画面（サーバー側で HTML を組む。検索エンジンに中身が見えるように）。

ライトテーマ固定・外部の JS を使わない・スマホ 320px でも横にはみ出さない。
リンクは公開先の絶対 URL（BASE）で書く。中継（khouan.php/）の下で相対パスがずれないように。
"""
from __future__ import annotations

import html
import json
import os

BASE = os.environ.get("KHOUAN_PUBLIC_BASE", "https://kurage.exbridge.jp/khouan.php").rstrip("/")
NAME = "Kurage 法案AIインタビュー"
LOGO = "https://exbridge.jp/images/logo-mark-128.png"
MASCOT = "https://kurage.exbridge.jp/images/kurage_mascot_simple_v2.png"
OGP = f"{BASE}/ogp.png"
GITHUB = "https://github.com/katsushi2441/khouan"
GIIN = "https://xb4g.com/giin"
KRONTEN = "https://kurage.exbridge.jp/kronten.php/"
KCONSENSUS = "https://kurage.exbridge.jp/kconsensus.php/"
STORE = "https://kappstore.exbridge.jp/app.php?id=b80a258f26c448d5#ref=khouan-store"   # 自社のサーバーに置く版（Kurage App Store）


def h(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def jdate(d: str) -> str:
    if not d:
        return ""
    p = (d[:10].split("-") + ["", "", ""])[:3]
    try:
        return f"{int(p[0])}年{int(p[1])}月{int(p[2])}日"
    except ValueError:
        return d


def short_name(b: dict, n: int = 24) -> str:
    s = b.get("law_name") or b["title"]
    return s if len(s) <= n else s[: n - 1] + "…"


CSS = """
:root{--ink:#12202f;--teal:#0a9a8f;--teal2:#e6f4f2;--line:#dfe7ec;--mut:#5d6b7a;--bg:#f5f8fa;--warn:#b5482a;color-scheme:light}
*{box-sizing:border-box;min-width:0}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans JP",system-ui,-apple-system,"Hiragino Sans",sans-serif;line-height:1.8}
a{color:var(--teal)}
header.top{background:#fff;border-bottom:1px solid var(--line)}
.hd{max-width:880px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:10px}
.hd a{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;font-weight:900}
.hd img{width:34px;height:34px;object-fit:contain;flex:none}
.wrap{max-width:880px;margin:0 auto;padding:20px 16px 70px;overflow-wrap:anywhere}
.crumb{font-size:12.5px;color:var(--mut);margin:0 0 8px}
.crumb a{color:var(--mut)}
.kick{color:var(--teal);font-weight:700;letter-spacing:.09em;font-size:12px;margin:0}
h1{font-size:clamp(21px,4.6vw,30px);margin:.2em 0 .3em;font-weight:900;line-height:1.45}
h2{font-size:clamp(18px,3.6vw,21px);margin:0 0 .5em;line-height:1.5}
h3{font-size:16px;margin:.6em 0 .3em}
.lead{color:var(--mut);margin:.3em 0 1em}
.hero{display:flex;gap:16px;align-items:flex-start}
.hero img.m{width:96px;height:auto;object-fit:contain;flex:none}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 2px 10px rgba(18,32,47,.05);margin:0 0 16px}
.pill{display:inline-block;font-size:12px;font-weight:700;border-radius:99px;padding:1px 10px;background:var(--teal2);color:#0a726b;margin:0 4px 4px 0;white-space:nowrap}
.pill.g{background:#eef2f5;color:var(--mut)}
.pill.w{background:#fdeee9;color:var(--warn)}
.note{color:var(--mut);font-size:13px}
.btn{display:inline-block;background:var(--teal);color:#fff;font-weight:800;padding:11px 20px;border-radius:99px;text-decoration:none;border:0;font-size:15px;cursor:pointer;font-family:inherit}
.btn.o{background:#fff;color:var(--teal);border:1.5px solid var(--teal)}
.btn:disabled{opacity:.5;cursor:default}
.bills{display:grid;gap:12px}
.bill{display:block;background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px;color:var(--ink);text-decoration:none}
.bill b{display:block;font-size:16px;line-height:1.55}
.bill .meta{font-size:12.5px;color:var(--mut);margin-top:4px}
.bill:hover{border-color:var(--teal)}
ul.ex{margin:6px 0 8px;padding-left:1.2em} ul.ex li{margin:4px 0}
table.tl{width:100%;border-collapse:collapse;table-layout:fixed;font-size:14px}
.tl th,.tl td{border-bottom:1px solid var(--line);padding:6px 4px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
.tl th{width:8.6em;color:var(--mut);font-weight:700}
.sp{border-left:3px solid var(--line);padding:2px 0 2px 12px;margin:12px 0}
.sp .m{font-size:12.5px;color:var(--mut)} .sp p{margin:4px 0;font-size:14px}
.cta{background:linear-gradient(135deg,#e6f4f2,#f3faf9);border:1.5px solid #bfe3de}
.topic{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}
.topic b.n{font-size:16px} .topic .sz{color:var(--mut);font-size:12.5px;margin-left:6px}
.topic ul{margin:6px 0 0;padding-left:1.2em;font-size:14px}
.ops{font-size:14px;padding-left:1.2em;margin:6px 0}
.ops li{margin:6px 0}
.steps{padding-left:1.3em} .steps li{margin:6px 0}
.faq dt{font-weight:800;margin-top:10px} .faq dd{margin:2px 0 0;color:#2b3a49}
.g3{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.g3 .card{margin:0}
.search{display:flex;gap:8px;margin:0 0 12px}
.search input{flex:1;font-size:16px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;font-family:inherit}
footer.ft{max-width:880px;margin:0 auto;padding:0 16px 40px;color:var(--mut);font-size:13px}
/* インタビュー */
.chat{display:flex;flex-direction:column;gap:10px;margin:8px 0 12px}
.msg{max-width:88%;padding:10px 14px;border-radius:14px;white-space:pre-wrap;font-size:15px;line-height:1.7}
.msg.ai{background:#fff;border:1px solid var(--line);align-self:flex-start;border-top-left-radius:4px}
.msg.user{background:var(--teal);color:#fff;align-self:flex-end;border-top-right-radius:4px}
.msg.sys{background:#fff8e6;border:1px solid #f0dca8;align-self:stretch;max-width:100%;font-size:13.5px}
.aiwho{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut);margin-bottom:2px}
.aiwho img{width:22px;height:22px;object-fit:contain}
.compose textarea,.rep textarea{width:100%;font-size:16px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;font-family:inherit;line-height:1.7;resize:vertical}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
.cnt{font-size:12px;color:var(--mut);margin-left:auto}
.prog{height:6px;background:#eef2f5;border-radius:4px;overflow:hidden;margin:4px 0 10px}
.prog span{display:block;height:100%;background:var(--teal);width:0;transition:width .3s}
.rep dl{margin:0} .rep dt{font-size:12.5px;color:var(--mut);font-weight:700;margin-top:10px} .rep dd{margin:2px 0 0}
.choice label{display:flex;gap:8px;align-items:flex-start;margin:8px 0;font-size:15px}
.choice input{margin-top:6px;flex:none}
.hide{display:none}
@media(max-width:560px){.hero img.m{width:64px}.msg{max-width:94%}.tl th{width:6.8em}}
"""


def page(title: str, desc: str, path: str, body: str, *, crumbs=None, jsonld=None, noindex=False,
         og_type="website", script="") -> str:
    url = f"{BASE}{path}"
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": NAME, "url": f"{BASE}/",
           "inLanguage": "ja", "publisher": {"@type": "Organization", "name": "株式会社エクスブリッジ", "url": "https://exbridge.jp/"},
           "potentialAction": {"@type": "SearchAction", "target": f"{BASE}/?q={{search_term_string}}",
                               "query-input": "required name=search_term_string"}}]
    if crumbs:
        ld.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i, "name": n, "item": u} for i, (n, u) in enumerate(crumbs, 1)]})
    for x in jsonld or []:
        ld.append({"@context": "https://schema.org", **x})
    lds = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    cr = ""
    if crumbs:
        cr = '<nav class="crumb">' + " › ".join(
            (f'<a href="{h(u)}">{h(n)}</a>' if i < len(crumbs) - 1 else h(n)) for i, (n, u) in enumerate(crumbs)) + "</nav>"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{h(title)}</title>
<meta name="description" content="{h(desc)}">
{'<meta name="robots" content="noindex,follow">' if noindex else ''}
<link rel="canonical" href="{h(url)}">
<meta property="og:type" content="{og_type}"><meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{h(title)}"><meta property="og:description" content="{h(desc)}">
<meta property="og:url" content="{h(url)}"><meta property="og:image" content="{OGP}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:locale" content="ja_JP"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{LOGO}">
{lds}
<style>{CSS}</style>
</head><body>
<header class="top"><div class="hd"><a href="{BASE}/"><img src="{LOGO}" width="34" height="34" alt="株式会社エクスブリッジ">{NAME}</a></div></header>
<main class="wrap">{cr}{body}</main>
<footer class="ft">{NAME}は、株式会社エクスブリッジ（名古屋）が開発しているシステムです。
法案の説明は<a href="{GIIN}/#ref=khouan">愛知の国会議員 発言ログ</a>の法案ページ（参議院の議案情報・国会会議録検索システム）から、
意見のまとめと話題の名前は当社のサーバーの生成AI（gemma4）で作っています。外部のAIサービスには送っていません。
<a href="{BASE}/about">このシステムについて</a>　<a href="{GITHUB}">GitHub（MIT）</a>　<a href="{STORE}">導入する（Kurage App Store）</a></footer>
{script}
</body></html>"""


def status_pill(s: str) -> str:
    return f'<span class="pill">{h(s)}</span>'


# ── トップ ────────────────────────────────────────────

FAQ = [
    ("法案AIインタビューとは何ですか？",
     "国会で審議中の法案について、AIが質問し、あなたが答えると、答えに合わせて質問を重ね、最後に「意見のまとめ」を作るシステムです。まとめを確かめて同意したときだけ保存し、公開してよいかもあなたが選べます。"),
    ("名前や連絡先は聞かれますか？", "聞きません。ログインもありません。答えの中に氏名・住所・電話番号などを書かないでください。書かれていた場合は公開しません。"),
    ("集まった意見はどう使われますか？",
     "公開に同意された意見を、法案ごとに意味の近さで話題に分けて表示します。話題から賛否を問える論点を立て、Kurage 合意形成AI（合意点マップ）で、どこで意見が割れ、どこで一致しているかを見られるようにします。"),
    ("法案の説明は誰が書いていますか？",
     "参議院の議案情報にある法律案の「理由」や議案要旨から、当社のサーバーの生成AIが要約したものです。数字と日付は元の文と照らし合わせています。正確な内容は元の文書（PDF）で確かめてください。"),
    ("国会や議員に意見が届きますか？",
     "このシステムは国会の公式の窓口ではありません。公式に意見を届ける方法は請願です。法案ページから、審査している委員会の委員と請願の手続を確かめられます。"),
]


def index(bills: list[dict], q: str = "") -> str:
    items = "".join(f"""<a class="bill" href="{BASE}/b/{h(b['id'])}/"><b>{h(b['title'])}</b>
<div class="meta">{status_pill(b['status'])}<span class="pill g">{h(b['kind'])}</span> 提出 {h(jdate(b['submitted']))}
・公開された意見 {b['n_public']}件{('・話題 ' + str(b['n_topics'])) if b['n_topics'] else ''}</div></a>""" for b in bills)
    if not items:
        items = '<p class="note">該当する法案はありません。</p>'
    faq = "".join(f"<dt>{h(a)}</dt><dd>{h(b)}</dd>" for a, b in FAQ)
    body = f"""<div class="hero"><div>
<p class="kick">BILL AI INTERVIEW · 第222回国会</p>
<h1>審議中の法案への意見を、AIインタビューで</h1>
<p class="lead">いまの国会で審議されている法案を、国会の公開情報から解説します。AIの質問に答えていくと、あなたの考えが「意見のまとめ」になります。公開に同意された意見は、法案ごとに話題に束ね、どこで意見が割れ、どこで一致しているかまで見えるようにします。</p>
</div><img class="m" src="{MASCOT}" width="96" height="96" alt="Kurageさん"></div>
<section class="card"><h2>審議中の法案（{len(bills)}本）</h2>
<form class="search" action="{BASE}/" method="get"><input type="search" name="q" value="{h(q)}" placeholder="法案名で探す（例：政治資金、自動車、所得税）" aria-label="法案名で探す"><button class="btn" type="submit">探す</button></form>
<div class="bills">{items}</div></section>
<section class="card"><h2>しくみ</h2><div class="g3">
<div class="card"><h3>1. 法案を読む</h3><p class="note">法律案の「理由」や議案要旨の要約、審議の経過、国会での質疑と答弁の抜粋を、出典つきで並べます。</p></div>
<div class="card"><h3>2. AIに答える</h3><p class="note">賛否・理由・暮らしへの影響・懸念・提案を、5問前後で聞きます。答えに合わせて、AIが質問を重ねます。約5分です。</p></div>
<div class="card"><h3>3. 意見が話題になる</h3><p class="note">公開に同意された意見を、<a href="{KRONTEN}#ref=khouan">論点AIマップ</a>と同じ方式で話題に束ね、<a href="{KCONSENSUS}#ref=khouan">合意形成AI</a>で賛否の割れ方を出します。</p></div>
</div></section>
<section class="card"><h2>よくある質問</h2><dl class="faq">{faq}</dl></section>
<section class="card"><h2>議員事務所・自治体・団体で使う</h2>
<p>パブリックコメントや住民アンケート、条例案への意見募集を、同じしくみで行えます。意見の聞き取りから、話題のまとめ、合意点の発見までを、自社のサーバーの中だけで動かせます（外部のAIサービスに送りません）。</p>
<div class="row"><a class="btn" href="{STORE}">導入する（Kurage App Store）</a><a class="btn o" href="{GITHUB}">GitHub（MIT）でソースを見る</a></div></section>"""
    return page("法案への意見をAIインタビューで｜審議中の法案（第222回国会）",
                "いまの国会で審議中の法案を国会の公開情報から解説し、AIインタビューで意見を聞きます。公開に同意された意見を法案ごとに話題に束ね、合意形成AIで割れ方と一致点を出します。ログイン不要。",
                "/", body, jsonld=[{"@type": "FAQPage", "mainEntity": [
                    {"@type": "Question", "name": a, "acceptedAnswer": {"@type": "Answer", "text": b}} for a, b in FAQ]}])


# ── 法案ページ ────────────────────────────────────────

def topics_block(b: dict, topics: list[dict], recent: list[dict], n_public: int) -> str:
    if topics:
        cards = ""
        for t in topics:
            ops = "".join(f'<li>{h(r["summary"])} <a href="{BASE}/r/{h(r["id"])}">まとめを読む</a></li>' for r in t["examples"])
            cards += (f'<div class="topic"><b class="n">{h(t["name"])}</b><span class="sz">{t["size"]}件</span>'
                      f'<p style="margin:4px 0">{h(t["summary"])}</p><ul>{ops}</ul></div>')
        return (f'<p>公開に同意された意見 <b>{n_public}件</b> を、意味の近さで <b>{len(topics)}つ</b>の話題に分けました'
                f'（{h(jdate(topics[0]["built_at"]))}時点）。話題の名前と要約はAIが付けたものです。件数は意見の数で、賛成・反対の数ではありません。</p>{cards}')
    if recent:
        ops = "".join(f'<li><span class="pill g">{h(r["stance"])}</span>{h(r["summary"])} <a href="{BASE}/r/{h(r["id"])}">まとめを読む</a></li>' for r in recent)
        return (f'<p>公開に同意された意見は <b>{n_public}件</b> です。5件集まると、話題に分けて表示します。</p>'
                f'<ul class="ops">{ops}</ul>')
    return '<p>まだ公開された意見はありません。最初の意見を伝えてみませんか。</p>'


def bill_page(b: dict, speeches: list[dict], topics: list[dict], recent: list[dict], n_public: int,
              kc_url: str | None) -> str:
    bid = b["id"]
    ex = json.loads(b.get("explain") or "[]")
    src_name = "参議院の議案要旨" if b.get("explain_source") == "要旨" else "法律案の本文の「理由」"
    src_url = b.get("summary_url") if b.get("explain_source") == "要旨" else b.get("text_url")
    exl = "".join(f"<li>{h(x)}</li>" for x in ex)
    tl = "".join(f'<tr><th>{h(jdate(d) or "—")}</th><td>{h(w)}</td></tr>' for d, w in json.loads(b.get("timeline") or "[]"))
    sp = "".join(f"""<div class="sp"><div class="m">{h(jdate(s['date']))}・{h(s['house'])} {h(s['meeting'])}・{h(s['speaker'])}{('（' + h(s['position']) + '）') if s['position'] else ''}{'・答弁' if s['role'] == 'gov' else ''}</div>
<p>{h((s['excerpt'] or '')[:220])}{'…' if len(s['excerpt'] or '') > 220 else ''}</p><a class="note" href="{h(s['url'])}" rel="nofollow noopener" target="_blank">会議録で読む</a></div>""" for s in speeches[:6])
    giin_url = f"{GIIN}/bill/{bid}#ref=khouan"
    kc = (f'<p>公開された意見の話題から、賛成か反対かを問える論点を立てました。論点に賛否を押すと、意見のグループと、立場が違っても一致する点が出ます。</p>'
          f'<a class="btn o" href="{h(kc_url)}#ref=khouan">合意形成AIで賛否を押す</a>') if kc_url else \
         '<p class="note">意見が集まり、話題に分けられたら、話題から賛否を問える論点を立てて、Kurage 合意形成AI（合意点マップ）に渡します。それまでは準備中です。</p>'
    links = [("参議院 議案情報（経過）", b.get("url")), ("議案要旨（PDF）", b.get("summary_url")), ("法律案の本文（PDF）", b.get("text_url"))]
    prim = "".join(f'<li><a href="{h(u)}" rel="nofollow noopener" target="_blank">{h(n)}</a></li>' for n, u in links if u)
    name = b.get("law_name") or b["title"]
    body = f"""<p class="kick">BILL · 第{h(b['session'])}回国会 · {h(bid)}</p>
<h1>{h(b['title'])}への意見</h1>
<p>{status_pill(b['status'])}<span class="pill g">{h(b['kind'])}</span></p>
<p>{h(b['answer'])}</p>
<section class="card cta"><h2 style="margin-top:0">この法案に意見を伝える（AIインタビュー）</h2>
<p>AIが5問前後で、賛否・理由・暮らしへの影響・懸念・提案を聞きます。答えに合わせて質問を重ね、最後に「意見のまとめ」を作ります。まとめを確かめて同意したときだけ保存し、公開するかどうかも選べます。名前は聞きません。</p>
<a class="btn" href="{BASE}/b/{h(bid)}/interview">AIインタビューを始める（約5分）</a></section>
<section class="card"><h2>この法案で変わること <span class="pill g">AIによる要約</span></h2><ul class="ex">{exl}</ul>
<p class="note">{h(src_name)}から、当社のサーバーの生成AI（gemma4）が作った要約です（{h('愛知の国会議員 発言ログ')}の法案ページと同じもの）。数字と日付は元の文と照らし合わせ、合わないものは載せていません。正確な内容は元の文書で確かめてください。{f'<a href="{h(src_url)}" rel="nofollow noopener" target="_blank">元の文書（PDF）</a>' if src_url else ''}</p></section>
<section class="card"><h2>審議の経過</h2><table class="tl">{tl}</table>
{'<p class="note">' + h(b['sessions'].replace(',', '・')) + '回の国会に出ています。表はいちばん新しい会期の経過です。</p>' if ',' in (b.get('sessions') or '') else ''}</section>
<section class="card"><h2>国会での質疑・答弁</h2>{sp or '<p class="note">件名がそのまま出てくる発言は、まだ見つかっていません（委員会で審査されていない法案や、略称で呼ばれた発言は拾えていません）。</p>'}
<p class="note">国会会議録検索システムで件名をそのまま引いた発言の抜粋です。<a href="{h(giin_url)}">法案ページ（愛知の国会議員 発言ログ）</a>で、審査している委員会の委員と、請願で意見を届ける方法も見られます。</p></section>
<section class="card"><h2>みんなの意見（話題）</h2>{topics_block(b, topics, recent, n_public)}</section>
<section class="card"><h2>どこで割れて、どこで一致しているか</h2>{kc}</section>
<section class="card"><h2>一次情報</h2><ul>{prim}<li><a href="{h(giin_url)}">愛知の国会議員 発言ログ：この法案のページ</a></li></ul></section>"""
    title = f"{short_name(b, 19)}への意見｜AIインタビュー"
    desc = (f"{short_name(b, 40)}（{b['status']}）の要約と審議の経過、国会での質疑を読み、"
            f"AIインタビューで意見を伝えられます。公開された意見は話題に分けて表示します。")
    return page(title, desc, f"/b/{bid}/", body, og_type="article",
                crumbs=[(NAME, f"{BASE}/"), (short_name(b, 30), f"{BASE}/b/{bid}/")])


# ── インタビュー画面 ──────────────────────────────────

INTERVIEW_JS = r"""<script>
(function(){
const BID = document.body.dataset.bill;
const API = location.pathname.split('/b/')[0] + '/api/';
const MASCOT = document.body.dataset.mascot;
const $ = s => document.querySelector(s);
let SID = null, busy = false;
function add(role, text){
  const d = document.createElement('div'); d.className = 'msg ' + role;
  if (role === 'ai') { const w = document.createElement('div'); w.className='aiwho'; w.innerHTML = '<img src="'+MASCOT+'" alt="">Kurageさん（AI）'; d.appendChild(w); }
  const t = document.createElement('div'); t.textContent = text; d.appendChild(t);
  $('#chat').appendChild(d); d.scrollIntoView({behavior:'smooth', block:'end'});
}
function prog(p){ if (p) { $('#prog span').style.width = Math.round(100*p.n/p.total)+'%'; $('#pn').textContent = p.n+' / '+p.total+' 問'; } }
async function call(path, body){
  const r = await fetch(API + path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  let d = {}; try { d = await r.json(); } catch(e) {}
  if (!r.ok) throw new Error(d.detail || d.error || ('エラー ' + r.status));
  return d;
}
function wait(on){ busy = on; $('#send').disabled = on; $('#skip').disabled = on; $('#wait').classList.toggle('hide', !on); }
$('#start').onclick = async () => {
  if (!$('#agree0').checked) { alert('注意を読んで、チェックを入れてください'); return; }
  $('#start').disabled = true;
  try {
    const d = await call('interview/start', {bill_id: BID});
    SID = d.session_id; $('#intro').classList.add('hide'); $('#talk').classList.remove('hide');
    d.messages.forEach(m => add('ai', m.text)); prog(d.progress); $('#ans').focus();
  } catch(e) { alert(e.message); $('#start').disabled = false; }
};
async function send(text){
  if (busy || !SID) return;
  text = text.trim(); if (!text) return;
  add('user', text); $('#ans').value = ''; cnt(); wait(true);
  try {
    const d = await call('interview/' + SID + '/answer', {text});
    d.messages.forEach(m => add('ai', m.text)); prog(d.progress);
    if (d.done) { $('#compose').classList.add('hide'); await report(); }
  } catch(e) { add('sys', e.message); }
  wait(false);
}
async function report(){
  add('sys', 'ありがとうございました。いまの答えから「意見のまとめ」を作っています（20秒ほど）…'); wait(true);
  try {
    const d = await call('interview/' + SID + '/report');
    const r = d.draft;
    $('#r-stance').textContent = r.stance;
    $('#r-summary').value = r.summary;
    const dl = [['理由', (r.reasons||[]).join('／')], ['暮らしや仕事への影響', r.impact], ['懸念', r.concerns], ['提案', r.proposals]];
    $('#r-more').innerHTML = dl.filter(x => x[1]).map(x => '<dt>'+x[0]+'</dt><dd></dd>').join('');
    let i = 0; dl.filter(x => x[1]).forEach(x => { $('#r-more').querySelectorAll('dd')[i++].textContent = x[1]; });
    $('#rep').classList.remove('hide'); $('#rep').scrollIntoView({behavior:'smooth'});
  } catch(e) { add('sys', e.message + '（もう一度「まとめを作る」を押してください）'); $('#again').classList.remove('hide'); }
  wait(false);
}
$('#again').onclick = () => { $('#again').classList.add('hide'); report(); };
$('#send').onclick = () => send($('#ans').value);
$('#skip').onclick = () => send('答えない（スキップ）');
$('#ans').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send($('#ans').value); });
function cnt(){ $('#cnt').textContent = $('#ans').value.length + ' / 600字'; }
$('#ans').addEventListener('input', cnt);
$('#save').onclick = async () => {
  if (!$('#consent').checked) { alert('内容を確かめて、保存に同意するチェックを入れてください'); return; }
  const pub = document.querySelector('input[name=pub]:checked');
  if (!pub) { alert('公開するかどうかを選んでください'); return; }
  $('#save').disabled = true; $('#saving').classList.remove('hide');
  try {
    const d = await call('interview/' + SID + '/save', {summary: $('#r-summary').value, want_public: pub.value === '1', consent: true});
    $('#rep').classList.add('hide'); $('#fin').classList.remove('hide');
    $('#fin-msg').textContent = d.message; $('#fin-link').href = d.report_url; $('#fin').scrollIntoView({behavior:'smooth'});
  } catch(e) { alert(e.message); $('#save').disabled = false; }
  $('#saving').classList.add('hide');
};
})();
</script>"""


def interview_page(b: dict, n_q: int) -> str:
    bid = b["id"]
    body = f"""<p class="kick">AI INTERVIEW</p>
<h1>{h(short_name(b, 40))}への意見を聞かせてください</h1>
<p class="note">{h(b['title'])}（{h(b['status'])}）。法案の要約と審議の経過は<a href="{BASE}/b/{h(bid)}/">法案ページ</a>で読めます。</p>
<section class="card" id="intro"><h2>始める前に</h2>
<ul class="ops">
<li>AIが{n_q}問前後で、賛否・理由・暮らしへの影響・懸念・提案を聞きます。答えに合わせて、質問を重ねることがあります。</li>
<li><b>名前は聞きません。</b>答えの中に、氏名・住所・電話番号・勤務先など、個人が分かることを書かないでください。</li>
<li>最後に「意見のまとめ」を作ります。<b>内容を確かめて同意したときだけ保存</b>します。公開するかどうかも選べます。</li>
<li>公開を選んでも、悪口や個人情報などが含まれるとAIが判定した場合は公開しません。</li>
<li>このシステムは国会の公式の窓口ではありません。1回の答えは600字まで、同じ回線からのインタビューは1時間に6回までです。</li>
</ul>
<label class="row" style="font-size:15px"><input type="checkbox" id="agree0"> 上のことを読みました</label>
<div class="row"><button class="btn" id="start">インタビューを始める</button></div></section>
<section id="talk" class="hide">
<div class="prog" id="prog"><span></span></div><p class="note" style="margin:0" id="pn"></p>
<div class="chat" id="chat"></div>
<p class="note hide" id="wait">Kurageさんが考えています…</p>
<div class="compose" id="compose"><textarea id="ans" rows="3" maxlength="600" placeholder="ここに答えを書いてください"></textarea>
<div class="row"><button class="btn" id="send">送る</button><button class="btn o" id="skip">答えない</button><span class="cnt" id="cnt">0 / 600字</span></div></div>
<button class="btn o hide" id="again">まとめを作る</button>
</section>
<section class="card rep hide" id="rep"><h2>意見のまとめ（確認してください）</h2>
<p class="note">AIがあなたの答えから作ったまとめです。要点の文は書き直せます。</p>
<dl><dt>立場</dt><dd id="r-stance"></dd><dt>要点（書き直せます・300字まで）</dt><dd><textarea id="r-summary" rows="4" maxlength="300"></textarea></dd></dl>
<dl id="r-more"></dl>
<div class="choice"><p style="margin:14px 0 4px;font-weight:800">公開しますか？</p>
<label><input type="radio" name="pub" value="1"> 公開してよい（このページと法案ページの「みんなの意見」に出し、話題のまとめと合意形成AIの材料にします。名前は出ません）</label>
<label><input type="radio" name="pub" value="0"> 公開しない（保存だけ。あなたにだけ見えるリンクを出します）</label></div>
<label class="row" style="font-size:15px"><input type="checkbox" id="consent"> この内容で保存することに同意します</label>
<div class="row"><button class="btn" id="save">保存する</button><span class="note hide" id="saving">保存しています（公開の判定に10秒ほどかかります）…</span></div></section>
<section class="card hide" id="fin"><h2>保存しました</h2><p id="fin-msg"></p>
<div class="row"><a class="btn" id="fin-link" href="#">保存したまとめを見る</a><a class="btn o" href="{BASE}/b/{h(bid)}/">法案ページへ戻る</a></div></section>"""
    out = page(f"{short_name(b, 16)}への意見｜AIインタビュー回答",
               f"{b['title']}について、AIの質問に答えて意見のまとめを作る画面です。名前は聞きません。まとめを確かめて同意したときだけ保存し、公開するかどうかも選べます。",
               f"/b/{bid}/interview", body, noindex=True, script=INTERVIEW_JS,
               crumbs=[(NAME, f"{BASE}/"), (short_name(b, 30), f"{BASE}/b/{bid}/"), ("AIインタビュー", f"{BASE}/b/{bid}/interview")])
    return out.replace("<body>", f'<body data-bill="{h(bid)}" data-mascot="{MASCOT}">', 1)


# ── レポート ─────────────────────────────────────────

def report_page(r: dict, b: dict, private: bool) -> str:
    reasons = json.loads(r.get("reasons") or "[]")
    rows = [("理由", "／".join(reasons)), ("暮らしや仕事への影響", r.get("impact")), ("懸念", r.get("concerns")), ("提案", r.get("proposals"))]
    more = "".join(f"<dt>{h(k)}</dt><dd>{h(v)}</dd>" for k, v in rows if v)
    warn = ""
    if private:
        why = "あなたが公開しないを選んだため" if not r["want_public"] else f"公開の判定で止まったため（{r.get('moderation_reason') or ''}）"
        warn = f'<p class="pill w">非公開</p><p class="note">このまとめは公開していません（{h(why)}）。このページのURLを知っている人だけが見られます。</p>'
    body = f"""<p class="kick">OPINION REPORT</p>
<h1>{h(short_name(b, 40))}への意見のまとめ</h1>{warn}
<section class="card rep"><dl><dt>立場</dt><dd>{h(r['stance'])}</dd><dt>要点</dt><dd>{h(r['summary'])}</dd>{more}</dl>
<p class="note" style="margin-top:12px">{h(jdate(r['created_at']))}に、AIインタビューの答えからAI（gemma4）がまとめ、本人が確かめて保存したものです。名前は聞いていません。</p></section>
<section class="card"><p style="margin:0 0 8px">{h(b['title'])}（{h(b['status'])}）</p>
<div class="row"><a class="btn" href="{BASE}/b/{h(b['id'])}/interview">あなたも意見を伝える</a><a class="btn o" href="{BASE}/b/{h(b['id'])}/">法案ページとみんなの意見</a></div></section>"""
    return page(f"{short_name(b, 16)}への意見のまとめ｜AIインタビュー",
                f"{b['title']}について、AIインタビューで寄せられた意見のまとめです。立場・理由・暮らしへの影響・懸念・提案を、本人が確かめて保存しました。",
                f"/r/{r['id']}", body, noindex=True,
                crumbs=[(NAME, f"{BASE}/"), (short_name(b, 30), f"{BASE}/b/{b['id']}/"), ("意見のまとめ", f"{BASE}/r/{r['id']}")])


def about_page(n_bills: int) -> str:
    body = f"""<p class="kick">ABOUT</p><h1>このシステムについて</h1>
<section class="card"><h2>何をするシステムか</h2>
<p>国会で審議中の法案（いまは第222回国会の{n_bills}本）について、法案の解説・AIインタビューによる意見の聞き取り・意見の話題へのまとめ・合意点の発見までを、1つの流れで行うシステムです。チームみらいの「みらい議会」と同じ考え方を、当社の<a href="{GIIN}/#ref=khouan">国会の発言ログ</a>、<a href="{KRONTEN}#ref=khouan">論点AIマップ</a>、<a href="{KCONSENSUS}#ref=khouan">合意形成AI（合意点マップ）</a>と組み合わせて作りました。</p></section>
<section class="card"><h2>流れ</h2><ol class="steps">
<li><b>法案を読み込む</b>：参議院の議案情報と国会会議録から、法案の経過・要約・質疑の抜粋を取り込みます。要約は法律案の「理由」や議案要旨をAIが要約したもので、数字と日付は元の文と照らし合わせています。</li>
<li><b>聞く項目を作る</b>：法案ごとに、要約から5問前後の質問（賛否・理由・影響・懸念・提案）をAIが作って保存します。</li>
<li><b>AIインタビュー</b>：答えに合わせて、AIが質問を重ねます。最後に意見のまとめを作り、本人が確かめて同意したときだけ保存します。公開するかどうかは本人が選びます。</li>
<li><b>荒らし対策</b>：1回の答えは600字まで、同じ回線からは1時間に6回まで。公開を選んだまとめは、電話番号・メール・URLなどの形と、AIによる悪口・個人情報・宣伝の判定を通ったものだけを公開します。</li>
<li><b>話題に束ねる</b>：公開されたまとめを multilingual-e5-large で意味の近さに変え、KMeans で話題に分け、話題の名前と要約をAIが付けます（論点AIマップと同じ方式）。新しい意見は定期処理で足します。</li>
<li><b>合意形成AIへ渡す</b>：話題から賛否を問える論点を立てて合意形成AIに渡し、公開されたまとめから賛否を読み取ります。人が押した票と、まとめから読み取った賛否は分けて表示します。</li>
</ol></section>
<section class="card"><h2>使っている技術</h2>
<p>生成AIは当社のサーバーの gemma4（Ollama）。埋め込みは multilingual-e5-large（手元のCPU）。外部のAIサービスには送りません。画面と API は FastAPI、データは SQLite です。</p>
<p>API（読み取り専用）：<code>{BASE}/api/bill/&lt;法案ID&gt;/summary</code>（公開された意見の件数・話題ごとの件数と代表的な意見・合意形成AIのページ）</p>
<p>ソースコード：<a href="{GITHUB}">GitHub</a>（MIT）。自社のサーバーに置いて使う版は <a href="{STORE}">Kurage App Store</a> にあります。</p></section>"""
    return page("法案AIインタビューのしくみ｜Kurage",
                "国会で審議中の法案の解説、AIインタビューでの意見の聞き取り、意見の話題へのまとめ、合意形成AIでの合意点の発見までを、自社のサーバーの生成AIで行うシステムの説明です。",
                "/about", body, crumbs=[(NAME, f"{BASE}/"), ("このシステムについて", f"{BASE}/about")])
