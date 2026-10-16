"""Translation catalog tool, standard library + Django only (M10, D77).

Called by `python tasks.py messages` (and its `--check` form in CI). It is a plain Python
replacement for GNU gettext, so the Tamil catalog builds the same way on Windows and Linux.

GNU gettext (xgettext/msgmerge/msgfmt) is not installed on the Windows dev machine, so
Django's ``makemessages``/``compilemessages`` cannot run there. This module does the same
three jobs in pure Python, identically on every machine:

1. extract: msgids from templates (via Django's own ``templatize``, the code makemessages
   uses) and from Python files (``ast``; calls to gettext, gettext_lazy, _, gettext_noop,
   ngettext, pgettext and their lazy variants). Migrations and tests are skipped.
2. merge: write ``locale/<lang>/LC_MESSAGES/django.po``, keeping existing translations and
   flags, adding new msgids with an empty msgstr, dropping msgids no longer in the code.
3. compile: write ``django.mo`` (GNU .mo format, the logic of CPython's
   ``Tools/i18n/msgfmt.py``). Fuzzy and untranslated entries are left out, as msgfmt does.

Usage (from ``src/``): ``python -m config.catalog update`` (extract + merge + compile) or
``python -m config.catalog check`` (exit 1 if the .po or .mo is stale or a msgstr is
missing). ``python tasks.py messages`` runs ``update``.
"""

from __future__ import annotations

import ast
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
LANGUAGES = ("ta",)
DOMAIN = "django"
SKIP_DIRS = {"migrations", "__pycache__", "locale", "static"}

# function name -> (index of msgctxt or None, index of msgid, index of msgid_plural or None)
KEYWORDS: dict[str, tuple[int | None, int, int | None]] = {
    "gettext": (None, 0, None),
    "gettext_lazy": (None, 0, None),
    "gettext_noop": (None, 0, None),
    "_": (None, 0, None),
    "ngettext": (None, 0, 1),
    "ngettext_lazy": (None, 0, 1),
    "pgettext": (0, 1, None),
    "pgettext_lazy": (0, 1, None),
    "npgettext": (0, 1, 2),
    "npgettext_lazy": (0, 1, 2),
}
CALL_RE = re.compile(r"(?<![\w.])(" + "|".join(sorted(KEYWORDS, key=len, reverse=True)) + r")\(")
FORMAT_RE = re.compile(r"%(?:\([A-Za-z0-9_]+\))?[-#0 +]*\d*(?:\.\d+)?[sdifr]")

HEADER_COMMENT = """\
# Tamil translation of Verified Stays.
# MACHINE TRANSLATION - NEEDS REVIEW by a native Tamil speaker before any real use
# (docs/open-questions.md Q3, docs/ui-and-accessibility.md). Not checked by a person.
# Generated and merged by `python tasks.py messages` (src/config/catalog.py).
#"""

HEADER_FIELDS = {
    "ta": [
        ("Project-Id-Version", "verified-stays"),
        ("Language", "ta"),
        ("MIME-Version", "1.0"),
        ("Content-Type", "text/plain; charset=UTF-8"),
        ("Content-Transfer-Encoding", "8bit"),
        ("Plural-Forms", "nplurals=2; plural=(n != 1);"),
        ("X-Review-Status", "machine translation, needs review by a native speaker"),
    ]
}


@dataclass
class Entry:
    """One translatable string: the English text, its translation(s) and where it is used."""

    msgid: str
    msgid_plural: str | None = None
    msgctxt: str | None = None
    refs: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    msgstr: str = ""
    msgstr_plural: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str | None, str]:
        """The identity of this entry: context plus English text. Two entries with the same key
        are the same message."""
        return (self.msgctxt, self.msgid)

    @property
    def is_format(self) -> bool:
        """True if the text contains a %-placeholder, so the .po file gets a python-format flag."""
        return bool(FORMAT_RE.search(self.msgid + (self.msgid_plural or "")))

    @property
    def translations(self) -> list[str]:
        """The translated text: one string, or one per plural form."""
        return self.msgstr_plural if self.msgid_plural else [self.msgstr]

    @property
    def translated(self) -> bool:
        """True only when every form has a non-empty translation."""
        return all(t for t in self.translations) and bool(self.translations)


# ------------------------------------------------------------------ extraction


def _string_args(call: ast.Call) -> list[str | None]:
    """The positional arguments of a call: the text for string literals, None for anything
    else (a variable or an expression cannot be translated, so it is skipped later)."""
    out: list[str | None] = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
        else:
            out.append(None)
    return out


def _calls_in(tree: ast.AST) -> list[tuple[str, list[str | None]]]:
    """Every call in a Python file whose name is one of the gettext keywords."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in KEYWORDS:
            found.append((name, _string_args(node)))
    return found


def _entry_from_call(name: str, args: list[str | None]) -> Entry | None:
    """Build an Entry from one gettext call, or return None if the call cannot be translated
    (for example, its text is a variable)."""
    ctx_i, id_i, pl_i = KEYWORDS[name]
    try:
        msgid = args[id_i]
        msgctxt = args[ctx_i] if ctx_i is not None else None
        plural = args[pl_i] if pl_i is not None else None
    except IndexError:
        return None
    if not msgid or (ctx_i is not None and msgctxt is None) or (pl_i is not None and not plural):
        return None
    return Entry(msgid=msgid, msgid_plural=plural, msgctxt=msgctxt)


def _template_calls(text: str, origin: str) -> list[tuple[str, list[str | None]]]:
    """Run Django's templatize, then pick the gettext calls out of its output (placeholder
    text plus Python-style calls, not a valid module) by scanning each call to its closing
    parenthesis, skipping over string literals, and parsing that slice with ``ast``."""
    # The scan is needed because the templatize output is not valid Python as a whole, so ast
    # cannot parse it directly. Each call is cut out on its own and parsed as one expression.
    from django.utils.translation.template import templatize

    code = templatize(text, origin=origin)
    found = []
    for match in CALL_RE.finditer(code):
        i, depth, quote = match.end() - 1, 0, ""
        while i < len(code):
            ch = code[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = ""
            elif ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        call = ast.parse(code[match.start(1) : i + 1], mode="eval").body
        if isinstance(call, ast.Call):
            found.append((match.group(1), _string_args(call)))
    return found


def _source_files() -> list[Path]:
    """Templates and Python files that may hold translatable text. Skips migrations, locale,
    static and cache folders, plus this file, which names the gettext functions itself."""
    files = []
    # Sorted by POSIX path string so the .po order is the same on Windows and Linux.
    for path in sorted(SRC.rglob("*"), key=lambda p: p.relative_to(SRC).as_posix()):
        rel = path.relative_to(SRC)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]) or not path.is_file():
            continue
        if path.suffix in {".html", ".txt"} and "templates" in rel.parts:
            files.append(path)
        elif path.suffix == ".py" and rel.as_posix() != "config/catalog.py":
            files.append(path)
    return files


def extract() -> list[Entry]:
    """All translatable msgids in ``src/``, in first-seen order (sorted file walk).

    The same msgid used in several files is one entry whose refs list every file."""
    entries: dict[tuple[str | None, str], Entry] = {}
    for path in _source_files():
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            calls = _calls_in(ast.parse(text, filename=rel))
        else:
            calls = _template_calls(text, rel)
        for name, args in calls:
            new = _entry_from_call(name, args)
            if new is None:
                continue
            entry = entries.setdefault(new.key, new)
            if entry.msgid_plural is None and new.msgid_plural:
                entry.msgid_plural = new.msgid_plural
            if rel not in entry.refs:
                entry.refs.append(rel)
    return list(entries.values())


# ------------------------------------------------------------------ .po read/write


def _unquote(s: str) -> str:
    """Read a quoted .po string such as "text\\n" and return its real value."""
    return ast.literal_eval(s)


def _quote(s: str) -> str:
    """Write a value as a quoted .po string, escaping backslashes, quotes and newlines."""
    # Backslashes are escaped first, so the escapes added afterwards are not escaped again.
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def parse_po(text: str) -> tuple[dict[str, str], list[Entry]]:
    """Return (header fields, entries). Handles the subset this tool writes plus multi-line
    strings; obsolete ``#~`` entries are ignored."""
    entries: list[Entry] = []
    header: dict[str, str] = {}
    cur: dict = {}
    last: str | None = None

    def flush() -> None:
        nonlocal cur, last
        if "msgid" in cur:
            if cur["msgid"] == "" and cur.get("msgctxt") is None:
                for line in cur.get("msgstr", "").splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        header[k.strip()] = v.strip()
            else:
                plural = cur.get("msgstr_plural", {})
                entries.append(
                    Entry(
                        msgid=cur["msgid"],
                        msgid_plural=cur.get("msgid_plural"),
                        msgctxt=cur.get("msgctxt"),
                        refs=cur.get("refs", []),
                        flags=cur.get("flags", []),
                        msgstr=cur.get("msgstr", ""),
                        msgstr_plural=[plural[k] for k in sorted(plural)],
                    )
                )
        cur, last = {}, None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#~"):
            continue
        if line.startswith("#:"):
            if "msgid" in cur:
                flush()
            cur.setdefault("refs", []).extend(line[2:].split())
            continue
        if line.startswith("#,"):
            if "msgid" in cur:
                flush()
            cur.setdefault("flags", []).extend(f.strip() for f in line[2:].split(","))
            continue
        if line.startswith("#"):
            continue
        if line.startswith('"'):
            value = _unquote(line)
            if last and last.startswith("msgstr["):
                n = int(last[7:-1])
                cur["msgstr_plural"][n] += value
            elif last:
                cur[last] += value
            continue
        keyword, _, rest = line.partition(" ")
        if keyword in {"msgctxt", "msgid"} and "msgid" in cur:
            flush()  # a new entry starts without a blank line
        value = _unquote(rest)
        if keyword.startswith("msgstr["):
            cur.setdefault("msgstr_plural", {})[int(keyword[7:-1])] = value
        else:
            cur[keyword] = value
        last = keyword
    flush()
    return header, entries


def write_po(lang: str, entries: list[Entry]) -> str:
    """The full text of a .po file: header, then one block per entry."""
    out = [HEADER_COMMENT, 'msgid ""', 'msgstr ""']
    out += [_quote(f"{k}: {v}\n") for k, v in HEADER_FIELDS[lang]]
    for e in entries:
        out.append("")
        out.append("#: " + " ".join(e.refs))
        flags = [f for f in e.flags if f and f != "python-format"]
        if e.is_format:
            flags.append("python-format")
        if flags:
            out.append("#, " + ", ".join(sorted(set(flags))))
        if e.msgctxt is not None:
            out.append("msgctxt " + _quote(e.msgctxt))
        out.append("msgid " + _quote(e.msgid))
        if e.msgid_plural:
            out.append("msgid_plural " + _quote(e.msgid_plural))
            plurals = e.msgstr_plural or ["", ""]
            out += [f"msgstr[{i}] " + _quote(s) for i, s in enumerate(plurals)]
        else:
            out.append("msgstr " + _quote(e.msgstr))
    return "\n".join(out) + "\n"


def merge(extracted: list[Entry], existing: list[Entry]) -> list[Entry]:
    """Keep the translations already in the .po for strings that still exist in the code.
    Strings no longer in the code are dropped; new strings start with an empty translation."""
    old = {e.key: e for e in existing}
    merged = []
    for e in extracted:
        prev = old.get(e.key)
        new = Entry(e.msgid, e.msgid_plural, e.msgctxt, list(e.refs))
        if prev is not None:
            new.flags = [f for f in prev.flags if f != "python-format"]
            new.msgstr = prev.msgstr
            new.msgstr_plural = list(prev.msgstr_plural)
            if bool(prev.msgid_plural) != bool(e.msgid_plural):
                new.msgstr, new.msgstr_plural = "", []
        merged.append(new)
    return merged


# ------------------------------------------------------------------ .mo


def compile_mo(header: list[tuple[str, str]], entries: list[Entry]) -> bytes:
    """GNU .mo bytes (little endian, no hash table), as CPython's Tools/i18n/msgfmt.py."""
    messages: dict[bytes, bytes] = {b"": "".join(f"{k}: {v}\n" for k, v in header).encode("utf-8")}
    for e in entries:
        if "fuzzy" in e.flags or not e.translated:
            continue
        key = e.msgid if e.msgctxt is None else f"{e.msgctxt}\x04{e.msgid}"
        if e.msgid_plural:
            key += "\x00" + e.msgid_plural
            value = "\x00".join(e.msgstr_plural)
        else:
            value = e.msgstr
        messages[key.encode("utf-8")] = value.encode("utf-8")
    keys = sorted(messages)
    ids = strs = b""
    offsets = []
    for k in keys:
        offsets.append((len(ids), len(k), len(strs), len(messages[k])))
        ids += k + b"\0"
        strs += messages[k] + b"\0"
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets: list[int] = []
    voffsets: list[int] = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    output += struct.pack(f"{len(koffsets)}i", *koffsets)
    output += struct.pack(f"{len(voffsets)}i", *voffsets)
    return output + ids + strs


# ------------------------------------------------------------------ commands


def po_path(lang: str) -> Path:
    """Where the .po file for `lang` lives (the standard Django locale folder)."""
    return SRC / "locale" / lang / "LC_MESSAGES" / f"{DOMAIN}.po"


def load(lang: str) -> list[Entry]:
    """The entries of the existing .po file, or an empty list if it does not exist yet."""
    path = po_path(lang)
    return parse_po(path.read_text(encoding="utf-8"))[1] if path.is_file() else []


def build(lang: str) -> tuple[str, bytes, list[Entry]]:
    """Produce the new .po text, the compiled .mo bytes and the merged entries, without writing
    anything. `check` compares these with the files on disk."""
    merged = merge(extract(), load(lang))
    return write_po(lang, merged), compile_mo(HEADER_FIELDS[lang], merged), merged


def update() -> int:
    """Write the .po and .mo files for every language and print a short summary. Returns 0."""
    for lang in LANGUAGES:
        old_keys = {e.key for e in load(lang)}
        po, mo, merged = build(lang)
        path = po_path(lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(po, encoding="utf-8", newline="\n")
        path.with_suffix(".mo").write_bytes(mo)
        new_keys = {e.key for e in merged}
        missing = [e.msgid for e in merged if not e.translated]
        print(
            f"{lang}: {len(merged)} msgids ({len(new_keys - old_keys)} new, "
            f"{len(old_keys - new_keys)} removed), {len(missing)} without a translation"
        )
    return 0


def check() -> int:
    """Fail (return 1) if a generated file is out of date or a Tamil string is missing.
    Used by `python tasks.py messages --check` in CI."""
    problems = []
    for lang in LANGUAGES:
        po, mo, merged = build(lang)
        path = po_path(lang)
        if not path.is_file() or path.read_text(encoding="utf-8") != po:
            problems.append(f"{path.relative_to(SRC)} is stale: run `python tasks.py messages`")
        mo_path = path.with_suffix(".mo")
        if not mo_path.is_file() or mo_path.read_bytes() != mo:
            problems.append(f"{mo_path.relative_to(SRC)} is stale: run `python tasks.py messages`")
        problems += [f"{lang}: no translation for {e.msgid!r}" for e in merged if not e.translated]
    print("\n".join(problems) or "catalog up to date")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    """Run the command named in argv[1]. Returns 2 for a wrong command name."""
    commands = {"update": update, "check": check}
    if len(argv) != 2 or argv[1] not in commands:
        print("Usage: python -m config.catalog <update|check>")
        return 2
    return commands[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
