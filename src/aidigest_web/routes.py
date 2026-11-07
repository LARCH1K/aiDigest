"""Маршруты сайта. Данные только читаются из базы пайплайна."""
from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path

from flask import Flask, abort, current_app, render_template, request, send_file

from aidigest.export_excel import export_xlsx, metric_line
from aidigest.models import ConfirmationStatus, Flag, Level
from aidigest.store import CaseStore
from aidigest_web.views import FLAG_HELP, STATUS_CLASS, STATUS_LABEL, filter_cases, headline


def _store() -> CaseStore:
    return CaseStore(Path(current_app.config["DATA_DIR"]) / "cases.json")


def _updated_at() -> datetime | None:
    p = Path(current_app.config["DATA_DIR"]) / "cases.json"
    return datetime.fromtimestamp(p.stat().st_mtime) if p.exists() else None


def init(app: Flask) -> None:
    app.jinja_env.globals.update(STATUS_CLASS=STATUS_CLASS, STATUS_LABEL=STATUS_LABEL, FLAG_HELP=FLAG_HELP,
                                 metric_line=metric_line, headline=headline, Flag=Flag)

    @app.route("/")
    def cases():
        all_cases = _store().load().cases
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
        found = next((c for c in _store().load().cases if c.id == case_id), None)
        if found is None:
            abort(404)
        return render_template("case.html", c=found)

    @app.route("/help")
    def help():
        return render_template("help.html", levels=list(Level))

    @app.route("/export.xlsx")
    def export():
        tmp = Path(tempfile.mkdtemp(prefix="aidigest_web_")) / "cases.xlsx"
        written = export_xlsx(_store().load().cases, None, tmp)
        return send_file(written, as_attachment=True,
                         download_name=f"aidigest_cases_{date.today().isoformat()}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404
