"""Маршруты сайта."""
from __future__ import annotations

from flask import Flask, render_template


def init(app: Flask) -> None:
    @app.route("/")
    def cases():
        return render_template("base.html")
