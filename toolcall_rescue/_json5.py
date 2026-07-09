"""A tiny, dependency-free tolerant JSON parser.

Standard ``json.loads`` rejects the "dirty" JSON that language models emit all
the time: single quotes, trailing commas, ``//`` and ``/* */`` comments, and
unquoted object keys. This module accepts a JSON5-ish superset so those outputs
can still be recovered.

It is intentionally small and self-contained. It is *not* a full JSON5
implementation (no hex numbers, no line-continuations inside strings) — it only
handles the leniencies that show up in real LLM tool-call output.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["loads", "JSON5Error"]


class JSON5Error(ValueError):
    """Raised when the input cannot be parsed even leniently."""


_WS = " \t\n\r\f\v"
_ID_START = re.compile(r"[A-Za-z_$]")
_ID_CHAR = re.compile(r"[A-Za-z0-9_$]")
_ESCAPES = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)

    def _err(self, msg: str) -> "JSON5Error":
        return JSON5Error(f"{msg} at position {self.i}")

    def _skip_ws(self) -> None:
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c in _WS:
                self.i += 1
            elif c == "/" and self.i + 1 < n and s[self.i + 1] == "/":
                self.i += 2
                while self.i < n and s[self.i] != "\n":
                    self.i += 1
            elif c == "/" and self.i + 1 < n and s[self.i + 1] == "*":
                self.i += 2
                while self.i + 1 < n and not (s[self.i] == "*" and s[self.i + 1] == "/"):
                    self.i += 1
                self.i += 2
            else:
                break

    def parse(self) -> Any:
        self._skip_ws()
        value = self._value()
        self._skip_ws()
        if self.i != self.n:
            raise self._err("unexpected trailing data")
        return value

    def _value(self) -> Any:
        self._skip_ws()
        if self.i >= self.n:
            raise self._err("unexpected end of input")
        c = self.s[self.i]
        if c == "{":
            return self._object()
        if c == "[":
            return self._array()
        if c in "\"'":
            return self._string()
        if c.isdigit() or c in "+-.":
            return self._number()
        return self._keyword()

    def _object(self) -> dict:
        self.i += 1  # consume '{'
        out: dict = {}
        while True:
            self._skip_ws()
            if self.i >= self.n:
                raise self._err("unterminated object")
            if self.s[self.i] == "}":  # empty or trailing comma
                self.i += 1
                return out
            key = self._key()
            self._skip_ws()
            if self.i >= self.n or self.s[self.i] != ":":
                raise self._err("expected ':' after object key")
            self.i += 1
            out[key] = self._value()
            self._skip_ws()
            if self.i >= self.n:
                raise self._err("unterminated object")
            c = self.s[self.i]
            if c == ",":
                self.i += 1
                continue
            if c == "}":
                self.i += 1
                return out
            raise self._err("expected ',' or '}' in object")

    def _key(self) -> str:
        c = self.s[self.i]
        if c in "\"'":
            return self._string()
        if _ID_START.match(c):
            start = self.i
            self.i += 1
            while self.i < self.n and _ID_CHAR.match(self.s[self.i]):
                self.i += 1
            return self.s[start : self.i]
        raise self._err("invalid object key")

    def _array(self) -> list:
        self.i += 1  # consume '['
        out: list = []
        while True:
            self._skip_ws()
            if self.i >= self.n:
                raise self._err("unterminated array")
            if self.s[self.i] == "]":  # empty or trailing comma
                self.i += 1
                return out
            out.append(self._value())
            self._skip_ws()
            if self.i >= self.n:
                raise self._err("unterminated array")
            c = self.s[self.i]
            if c == ",":
                self.i += 1
                continue
            if c == "]":
                self.i += 1
                return out
            raise self._err("expected ',' or ']' in array")

    def _string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        buf: list[str] = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self.i += 1
                if self.i >= self.n:
                    raise self._err("bad escape sequence")
                e = self.s[self.i]
                if e in _ESCAPES:
                    buf.append(_ESCAPES[e])
                    self.i += 1
                elif e == "u":
                    hexs = self.s[self.i + 1 : self.i + 5]
                    if len(hexs) < 4:
                        raise self._err("bad \\u escape")
                    try:
                        buf.append(chr(int(hexs, 16)))
                    except ValueError as exc:
                        raise self._err("bad \\u escape") from exc
                    self.i += 5
                else:
                    # Unknown escape: keep the character literally.
                    buf.append(e)
                    self.i += 1
            elif c == quote:
                self.i += 1
                return "".join(buf)
            else:
                buf.append(c)
                self.i += 1
        raise self._err("unterminated string")

    def _number(self):
        start = self.i
        s, n = self.s, self.n
        if s[self.i] in "+-":
            self.i += 1
        while self.i < n and (s[self.i].isdigit() or s[self.i] in ".eE+-"):
            self.i += 1
        text = s[start : self.i]
        try:
            if any(ch in text for ch in ".eE"):
                return float(text)
            return int(text)
        except ValueError as exc:
            raise self._err(f"invalid number {text!r}") from exc

    def _keyword(self):
        s = self.s
        for word, value in (
            ("true", True),
            ("false", False),
            ("null", None),
            ("True", True),
            ("False", False),
            ("None", None),
        ):
            if s.startswith(word, self.i):
                self.i += len(word)
                return value
        raise self._err("unexpected token")


def loads(text: str) -> Any:
    """Parse *text* as tolerant (JSON5-ish) JSON. Raises :class:`JSON5Error`."""
    return _Parser(text).parse()
