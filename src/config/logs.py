"""Structured (JSON lines) logging with personal data scrubbed (M11, D84).

Sentry is not added (dependency not approved; cut order item 4). Errors go to stdout as one
JSON object per line, which the host's log viewer keeps. Two layers keep personal data out:

1. ``JsonFormatter`` writes a fixed set of fields only (time, level, logger, message, status
   code, exception text). It never serialises the ``request`` object Django attaches to
   ``django.request`` records, so client addresses, headers, cookies and form data are not
   written.
2. ``scrub()`` runs over every string written, and ``ScrubFilter`` over the message for any
   other handler: IPv4/IPv6 addresses, e-mail addresses, Indian mobile numbers, credentials in
   URLs and ``password=``/``token=``-style values are replaced by placeholders.

This is a safety net, not a licence to log personal data: code must still not log it.
"""

import json
import logging
import re
from datetime import UTC, datetime

_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_HEX = r"[0-9A-Fa-f]{1,4}"
_IPV6 = re.compile(
    rf"(?<![\w:])(?:(?:{_HEX}:){{7}}{_HEX}"
    rf"|(?:{_HEX}(?::{_HEX})*)?::(?:{_HEX}(?::{_HEX})*)?(?::\[ip\])?)(?![\w:])"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@", re.IGNORECASE)
_SECRET_VALUE = re.compile(
    r"\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|cookie|sessionid|"
    r"csrftoken|csrfmiddlewaretoken)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{9}(?!\d)")


def scrub(text: str) -> str:
    """Replace personal data and secrets in ``text`` with placeholders."""
    text = _URL_CREDENTIALS.sub(r"\1[redacted]@", text)
    text = _SECRET_VALUE.sub(r"\1\2[redacted]", text)
    text = _EMAIL.sub("[email]", text)
    text = _IPV4.sub("[ip]", text)
    text = _IPV6.sub("[ip]", text)
    return _PHONE.sub("[phone]", text)


class ScrubFilter(logging.Filter):
    """Scrubs the formatted message in place (for any handler, not only ``JsonFormatter``)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line with a fixed field set; every string is scrubbed."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        status_code = getattr(record, "status_code", None)
        if isinstance(status_code, int):
            entry["status_code"] = status_code
        if record.exc_info:
            entry["exc"] = scrub(self.formatException(record.exc_info))
        elif record.exc_text:
            entry["exc"] = scrub(record.exc_text)
        return json.dumps(entry, ensure_ascii=False)
