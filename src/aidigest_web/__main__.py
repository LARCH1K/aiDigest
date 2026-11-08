"""Запуск фронта: python -m aidigest_web [--host 0.0.0.0] [--port 8000]."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from aidigest_web import PROJECT_ROOT, create_app

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _web_env() -> dict[str, str]:
    from aidigest.creds import WEB_KEYS, load_creds
    return load_creds(PROJECT_ROOT / "web.env", WEB_KEYS)


def _serve(app, host: str, port: int) -> None:
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="aidigest_web", description="Веб-интерфейс aiDigest")
    p.add_argument("--host", default="127.0.0.1", help="адрес; 0.0.0.0 — открыть в локальную сеть (нужен пароль)")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    env = _web_env()
    password = env.get("WEB_PASSWORD") or None
    if args.host not in LOCAL_HOSTS and not password:
        print("Открыть сайт в сеть без пароля нельзя: задайте WEB_PASSWORD (файл web.env в корне проекта или переменная окружения).")
        return 2
    if args.host not in LOCAL_HOSTS and not env.get("WEB_SECRET_KEY"):
        print("Открыть сайт в сеть без постоянного ключа нельзя: задайте WEB_SECRET_KEY "
              "(иначе каждая перевыкладка разлогинивает пользователей).")
        return 2
    data_dir = Path(os.environ.get("AIDIGEST_DATA_DIR") or PROJECT_ROOT / "data")
    app = create_app(data_dir, password, env.get("WEB_SECRET_KEY"))
    shown = "localhost" if args.host in LOCAL_HOSTS else args.host
    print(f"aiDigest: http://{shown}:{args.port}/" + ("" if password else "  (без пароля, только этот компьютер)"))
    _serve(app, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
