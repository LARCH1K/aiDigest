"""Маршруты сайта. Данные только читаются из базы пайплайна."""
from __future__ import annotations

import io
import tempfile
from urllib.parse import urlsplit
from datetime import date, datetime
from pathlib import Path

from flask import (Flask, Response, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)

from aidigest.export_excel import export_xlsx, metric_line
from aidigest.models import ConfirmationStatus, Flag, Level
from aidigest.store import CaseStore
from aidigest_web.runs import AlreadyRunning, MonthExhausted
from aidigest_web.views import FLAG_HELP, STATUS_CLASS, STATUS_LABEL, filter_cases, headline


def _store() -> CaseStore:
    return CaseStore(Path(current_app.config["DATA_DIR"]) / "cases.json")


def _load_cases() -> tuple[list, bool]:
    """Кейсы базы и признак «файл базы повреждён» (пустой или нечитаемый) — без ошибки 500."""
    try:
        return _store().load().cases, False
    except (ValueError, OSError):
        return [], True


def safe_url(url: str | None) -> str:
    """В ссылку попадают только http(s)-адреса: «javascript:» из данных не должен стать ссылкой."""
    try:
        return url if url and urlsplit(url).scheme in ("http", "https") else "#"
    except ValueError:
        return "#"


def _updated_at() -> datetime | None:
    p = Path(current_app.config["DATA_DIR"]) / "cases.json"
    return datetime.fromtimestamp(p.stat().st_mtime) if p.exists() else None


def init(app: Flask) -> None:
    app.jinja_env.filters["safe_url"] = safe_url
    app.jinja_env.globals.update(STATUS_CLASS=STATUS_CLASS, STATUS_LABEL=STATUS_LABEL, FLAG_HELP=FLAG_HELP,
                                 metric_line=metric_line, headline=headline, Flag=Flag)

    @app.route("/")
    def cases():
        all_cases, broken = _load_cases()
        if broken:
            flash("Файл базы кейсов повреждён или пуст — запустите сбор, чтобы пересобрать данные.", "bad")
        args = request.args
        f = {
            "q": args.get("q", "").strip(),
            "level": args.get("level", ""),
            "status": args.get("status", ""),
            "metrics": args.get("metrics", "1") != "0",
            "doubtful": args.get("doubtful") == "1",
        }
        shown = filter_cases(all_cases, q=f["q"], level=f["level"], status=f["status"],
                             with_metrics=f["metrics"], hide_doubtful=f["doubtful"])
        return render_template("cases.html", cases=shown, total=len(all_cases), f=f, updated=_updated_at(),
                               levels=list(Level), statuses=list(ConfirmationStatus))

    @app.route("/case/<case_id>")
    def case(case_id: str):
        found = next((c for c in _load_cases()[0] if c.id == case_id), None)
        if found is None:
            abort(404)
        return render_template("case.html", c=found)

    @app.route("/help")
    def help():
        return render_template("help.html", levels=list(Level))

    @app.route("/export.xlsx")
    def export():
        with tempfile.TemporaryDirectory(prefix="aidigest_web_") as tmp:
            written = export_xlsx(_load_cases()[0], None, Path(tmp) / "cases.xlsx")
            data = io.BytesIO(written.read_bytes())
        return send_file(data, as_attachment=True,
                         download_name=f"aidigest_cases_{date.today().isoformat()}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def _runs():
        return current_app.extensions["runs"]

    @app.route("/run", methods=["GET", "POST"])
    def run():
        rm = _runs()
        if request.method == "POST":
            try:
                rm.start()
                flash("Сбор запущен. Это займёт 5–15 минут — страницу можно закрыть и вернуться.", "ok")
            except AlreadyRunning:
                flash("Сбор уже идёт — дождитесь, пока он закончится.", "warn")
            except MonthExhausted:
                flash("Лимит кредитов Tavily исчерпан — новый сбор возможен после пополнения лимита.", "bad")
            return redirect(url_for("run"))
        current = rm.current()
        history = rm.history(10)
        credits = rm.credits()
        spent, limit = credits["spent"], credits["limit"]
        return render_template("run.html", current=current, tail=rm.tail(current) if current else [],
                               history=history, last=history[0] if history else None, credits_source=credits["source"],
                               spent=spent, limit=limit, remaining=max(0, limit - spent), run_budget=rm.run_budget())

    @app.route("/run/status")
    def run_status():
        rm = _runs()
        current = rm.current()
        if current is None:
            return jsonify(running=False)
        return jsonify(running=True, started=current.started.isoformat() if current.run_id else None,
                       minutes=current.minutes, tail=rm.tail(current))

    @app.route("/run/log/<run_id>")
    def run_log(run_id: str):
        text = _runs().log_text(run_id)
        if text is None:
            abort(404)
        return Response(text, mimetype="text/plain; charset=utf-8")

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404
