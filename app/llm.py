"""gemma4（0.3 の Ollama）を呼ぶ。外部のAIサービスには送らない。

- gemma4 は思考型なので "think": false を必ず付ける（付けないと response が空になる）。
- 返す形は JSON スキーマで縛る（"format": "json" だけだと型が崩れることがあった・kronten 2026-10-08）。
- 同時に投げるのは2本まで（0.3 の GPU を他の製品と分け合うため）。
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request

OLLAMA = os.environ.get("KHOUAN_OLLAMA", "http://192.168.0.3:11434")
MODEL = os.environ.get("KHOUAN_LLM", "gemma4:12b-it-qat")
_SEM = threading.Semaphore(int(os.environ.get("KHOUAN_LLM_CONCURRENCY", "2")))


class LLMError(RuntimeError):
    pass


def ask_json(prompt: str, schema: dict, *, temperature: float = 0.2, num_predict: int = 900,
             timeout: int = 150) -> dict:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "format": schema,
                       "think": False, "keep_alive": "30m",
                       "options": {"temperature": temperature, "num_predict": num_predict}}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    if not _SEM.acquire(timeout=timeout):
        raise LLMError("AIが混み合っています")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except Exception as e:  # noqa: BLE001
        raise LLMError(str(e)[:200]) from e
    finally:
        _SEM.release()
    try:
        return json.loads(d.get("response") or "{}")
    except json.JSONDecodeError as e:
        raise LLMError("AIの応答を読めませんでした") from e


def text(x) -> str:
    """{"name": {"text": ...}} のような入れ子で返っても文字列を取り出す。"""
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict):
        return next((text(v) for v in x.values() if text(v)), "")
    if isinstance(x, list):
        return "、".join(t for t in (text(v) for v in x) if t)
    return ""
