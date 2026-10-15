# Kurage 法案AIインタビュー（khouan）

国会で審議中の法案を解説し、**AIインタビュー**で意見を聞き、公開に同意された意見を**話題に束ね**、話題から立てた論点を
[Kurage 合意形成AI（合意点マップ）](../kconsensus) に渡して、どこで意見が割れ、どこで一致しているかを出すシステム。
チームみらいの「みらい議会」（法案の解説→AIインタビュー→話題）と同じ流れを、当社の既存のシステムと組み合わせて作った。

公開: https://kurage.exbridge.jp/khouan.php/ （最初の範囲は第222回国会で審議中の法案）

## 流れ

| 段 | 中身 | 使うもの |
|---|---|---|
| 法案を読み込む | `scripts/import_bills.py`。xb4g/giin の `giin.sqlite`（bill・bill_speech）から、審議中（委員会で審査中を含む）の法案を写す。法案IDは giin と同じ（例 `222-san-1`） | 要約は giin の「この法案で変わること」（数字・日付は giin で照合済み）をそのまま使う。要約が無い法案は取り込まない |
| 聞く項目 | 法案ごとに5問前後（賛否・理由・影響・懸念・提案）を作って保存。作れなかったら決まった聞き方 | gemma4（JSON スキーマで型を縛る） |
| AIインタビュー | 答えに合わせて深掘りを最大3回。最後に「意見のまとめ」を作り、本人が確かめて同意したら保存。公開は本人が選ぶ | gemma4 |
| 荒らし対策 | 1回の答え600字・1回のインタビューで14回まで・回線ごとに開始6回/時・20回/日、全体300回/時。公開を選んだまとめは、電話・メール・郵便番号・URL の形と、gemma4 の判定（悪口・個人情報・宣伝）を通ったものだけ公開。判定できなければ公開しない | IP は塩つきハッシュだけ保存 |
| 話題に束ねる | `scripts/build_topics.py`。公開の意見が5件以上の法案だけ。意見の組が前回と同じなら作り直さない | multilingual-e5-large（fastembed・CPU）＋KMeans（random_state 固定）＋gemma4（話題名・要約・論点）。kronten と同じ方式 |
| 合意形成AIへ | `scripts/to_kconsensus.py --apply`。法案ごとに kconsensus の論点 `khouan-<法案ID>` を作り、話題の論点を渡す（ほぼ同文は埋め込みで、同じ主張かは gemma4 で判定。合わせて12本まで）。公開の意見を reaction（platform=AIインタビュー）として入れ、賛否の読み取りは kconsensus の `import_reactions.py --fill` | kronten の to_kconsensus.py と同じ型 |
| 条文への修正提案（2026-10-15〜） | `scripts/import_articles.py`。衆議院の議案本文情報（提出時の法律案・HTML）から条ごとに取り込む（番号の無い改正の文は「本則」、附則は「附則第◯条」。改正の文の中の書き換え後の条では切らない）。参議院のPDFしかない法案は取り込まず、PDFを案内する。条のページで市民が修正を提案し、AIが「第◯条中「A」を「B」に改める。」の形に整える手伝いをする。A は条文にある語句だけ使い、修正の文はプログラムで組み立てる。保存・公開の決まりは意見のまとめと同じ | gemma4（形に整えるところだけ） |
| 定期処理 | `scripts/refresh.py`（上の3つ＋新しい法案の条文の取り込み）。kdeck のゴール `khouan-refresh` → rqdb4ai `kurage-video-worker` → `kurage_web/backend/khouan_jobs.py` | 1日6回・4時間あけ |

## 画面と API

- `/` 審議中の法案の一覧（`?q=` で絞り込み）、`/b/<法案ID>/` 法案ページ（解説・インタビューへの入口・みんなの意見の話題・合意形成AI）、
  `/b/<法案ID>/interview` インタビュー、`/b/<法案ID>/a/<条の番号>` 条文と修正の提案（提案が無い条は noindex）、`/m/<id>` 提案1件（noindex）、`/r/<id>` 意見のまとめ（noindex。非公開のまとめは本人に渡す `?k=` 付きの URL でだけ見える）、`/about`
- `sitemap.xml`・`robots.txt`・`llms.txt`・`ogp.png`
- 修正提案: `POST /api/amend/draft`（要望→修正の形・回線ごとに10回/時）、`POST /api/amend/save`（6回/時・20回/日）
- 公開・読み取り専用: `GET /api/bill/<法案ID>/summary`（公開の意見の件数・話題ごとの件数と代表的な意見・合意形成AIのページURL・条ごとの修正提案の件数）、`GET /api/bills`。
  xb4g の `/giin/bill/<法案ID>` がサーバー側で読み、10分キャッシュして3つの枠を出す（`giin/lib/bills.php` の `g_bill_khouan`）

## 動かす

```bash
uv venv .venv --python /usr/bin/python3 && uv pip install --python .venv/bin/python fastapi==0.110.3 uvicorn==0.29.0 fastembed==0.9.0 scikit-learn==1.7.2 numpy pillow
.venv/bin/python scripts/import_bills.py                 # 法案と聞く項目
systemctl --user enable --now khouan                      # 0.0.0.0:18395（scripts/khouan.service）
/usr/bin/python3 scripts/deploy_php.py                     # heteml に khouan.php と khouan_config.php（合言葉）を置く
.venv/bin/python scripts/refresh.py                       # 定期処理を手で
.venv/bin/python scripts/admin.py list | hide <id> | mark-test <id> | delete-test
/usr/bin/python3 scripts/shot.py top https://kurage.exbridge.jp/khouan.php/ --full   # 320/360/390/1280px のはみ出し確認
/usr/bin/python3 scripts/e2e_interview.py 222-san-1        # 公開URLで1件通す確認（終わったら mark-test → delete-test）
```

`.env`（リポジトリに入れない）: `KHOUAN_RELAY_TOKEN`（中継の合言葉。これが付いたときだけ X-Forwarded-For を信じる）・`KHOUAN_SALT`（IP のハッシュの塩）。

## 決まり

- 生成AIは 0.3 の Ollama の `gemma4:12b-it-qat`（`think:false`）。外部のAIサービスには送らない。
- 法案の数字・事実を作らない。要約は giin のもの、聞く項目も要約に書いてあることだけを使う。
- 件数は「公開に同意された意見の数」で、世論調査ではない（画面と API に明記）。

ライセンス: MIT
