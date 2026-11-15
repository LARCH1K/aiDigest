"""Разбор вывода `aidigest run`: строки отчёта и причина неудачи. Работает с текстом лога, не с файлом."""
from __future__ import annotations

REPORT_PREFIXES = ("Кредитов", "Вызовов", "Статей", "Кандидатов", "Кейсов", "Подтверждений", "Бюджет", "Флаг:")
STATE_LABEL = {"running": "идёт", "ok": "успешно", "error": "ошибка", "limit": "месячный лимит исчерпан",
               "interrupted": "прервано"}
REASON_PREFIX = "Причина: "


def parse_report(log_text: str) -> dict[str, str]:
    """Строки отчёта CLI вида «Ключ: значение» (у флагов ключ сам содержит двоеточие)."""
    out: dict[str, str] = {}
    for line in log_text.splitlines():
        line = line.strip()
        if not line.startswith(REPORT_PREFIXES) or ": " not in line:
            continue
        key, value = line.rsplit(": ", 1)
        out[key] = value
    return out


def last_reason(log_text: str) -> str | None:
    """Последняя строка «Причина: …» из лога, без префикса."""
    for line in reversed(log_text.splitlines()):
        if line.startswith(REASON_PREFIX):
            return line[len(REASON_PREFIX):].strip() or None
    return None
