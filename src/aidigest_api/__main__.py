"""Запуск HTTP API командой python -m aidigest_api."""
import argparse
import os
import sys
from pathlib import Path

import uvicorn

from aidigest.creds import SECRETS_FILE, WEB_KEYS, load_creds
from aidigest.db.engine import make_engine
from aidigest_api import ROOT, create_app

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aidigest_api", description="HTTP API aiDigest")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    credentials = load_creds(ROOT / SECRETS_FILE, WEB_KEYS)
    username = credentials.get("WEB_USERNAME")
    password = credentials.get("WEB_PASSWORD")
    secret_key = credentials.get("WEB_SECRET_KEY")
    if args.host not in LOCAL_HOSTS:
        if not username or not password:
            print("Для запуска API в сети задайте WEB_USERNAME и WEB_PASSWORD.", file=sys.stderr)
            return 2
        if not secret_key:
            print("Для запуска API в сети задайте постоянный WEB_SECRET_KEY.", file=sys.stderr)
            return 2

    data_dir = Path(os.environ.get("AIDIGEST_DATA_DIR") or ROOT / "data")
    app = create_app(make_engine(), username=username, password=password, secret_key=secret_key,
                     secure_cookie=os.environ.get("AIDIGEST_SECURE_COOKIE") == "1", data_dir=data_dir,
                     trust_real_ip=os.environ.get("AIDIGEST_TRUST_REAL_IP") == "1")
    uvicorn.run(app, host=args.host, port=args.port, workers=1, proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
