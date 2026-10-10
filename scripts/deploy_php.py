#!/usr/bin/env python3
"""khouan.php（中継）と khouan_config.php（バックエンドと合言葉。リポジトリに入れない）を heteml に置く（1接続）。

  /usr/bin/python3 scripts/deploy_php.py
  /usr/bin/python3 scripts/deploy_php.py --php-only   # khouan.php だけ（設定を置き直さない）

送り先: /web/kurage_exbridge_jp/khouan.php と khouan_config.php
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.environ.get("KHOUAN_BACKEND", "http://exbridge.ddns.net:18395")


def env(path):
    e = {}
    for ln in open(path, encoding="utf-8"):
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            e[k] = v.strip('"\'')
    return e


def main():
    ftp = env("/home/kojima/work/aixec/.env")
    files = [(os.path.join(ROOT, "php", "khouan.php"), "khouan.php")]
    if "--php-only" not in sys.argv:
        tok = env(os.path.join(ROOT, ".env"))["KHOUAN_RELAY_TOKEN"]
        cfg = os.path.join(ROOT, "outputs", "khouan_config.php")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(f"<?php define('KHOUAN_BACKEND', '{BACKEND}'); define('KHOUAN_RELAY_TOKEN', '{tok}');\n")
        files.append((cfg, "khouan_config.php"))
    args = ["curl", "-sS", "-u", f"{ftp['FTP_USER']}:{ftp['FTP_PASS']}"]
    for src, dst in files:
        args += ["-T", src, f"ftp://{ftp['FTP_HOST']}/web/kurage_exbridge_jp/{dst}"]
    r = subprocess.run(args, capture_output=True, text=True)
    print("送信", "OK" if r.returncode == 0 else "失敗 " + r.stderr[-300:], [d for _, d in files])


if __name__ == "__main__":
    main()
