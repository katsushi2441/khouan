#!/usr/bin/env python3
"""定期処理（kdeck のゴール khouan-refresh → rqdb4ai → kurage_web/backend/khouan_jobs.py から呼ぶ）。

1. giin から審議中の法案を取り込み直す（新しい法案は聞く項目も作る。状態の変化も写す）
1.5 新しい法案の条文を条ごとに取り込む（条文への修正提案のため。取り込み済みの法案は飛ばす）
2. 公開に同意された意見を話題に束ね直す（意見の組が変わった法案だけ）
3. 話題のある法案は、論点を合意形成AIへ渡し、賛否の読み取りを足す（kconsensus の import_reactions.py --fill）

  .venv/bin/python scripts/refresh.py
最後の行に JSON（kdeck の契約: items）を出す。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")


def run(args, timeout):
    p = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{args[0]}: {p.stderr[-1500:]}")
    return p.stdout.strip().splitlines()


def main():
    out = {}
    out["import"] = run(["scripts/import_bills.py"], 1800)[0]
    out["articles"] = run(["-m", "scripts.import_articles"], 1800)[-5:]
    topics = json.loads(run(["scripts/build_topics.py"], 3600)[-1])
    out["topics"] = topics
    built = [b["bill"] for b in topics["built"]]
    if built:
        out["kconsensus"] = json.loads(run(["scripts/to_kconsensus.py", "--apply", "--bill", *built], 7200)[-1])
    print(json.dumps({"items": 1, "built": len(built), "result": out}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
