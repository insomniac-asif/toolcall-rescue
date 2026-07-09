"""Salvage tool/function calls that leaked into an LLM's message content.

Public API:

    rescue(content: str) -> list[dict]   # each {"name": str, "arguments": dict}
    strip(content: str) -> str           # content with the tool-call markup removed

See the module :func:`rescue` docstring and the project README for the list of
dialects handled.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import _json5

__all__ = ["rescue", "rescue_first", "strip", "normalize_fullwidth"]

Call = Dict[str, Any]
Span = Tuple[int, int]

# --------------------------------------------------------------------------- #
# Fullwidth normalization
# --------------------------------------------------------------------------- #
# Some models (notably DeepSeek) emit tool-call markup using fullwidth unicode
# delimiters instead of ASCII. These map 1:1 to their ASCII counterparts, so
# translating them preserves every character index.
_FULLWIDTH = {
    0xFF5C: 0x7C,  # ｜ -> |
    0xFF1C: 0x3C,  # ＜ -> <
    0xFF1E: 0x3E,  # ＞ -> >
}


def normalize_fullwidth(text: str) -> str:
    """Replace fullwidth ``｜＜＞`` with ASCII ``|<>`` (length-preserving)."""
    return text.translate(_FULLWIDTH)


# --------------------------------------------------------------------------- #
# Shared: turn a parsed JSON value into a list of calls
# --------------------------------------------------------------------------- #
_ARG_KEYS = ("arguments", "parameters", "args", "input")


def _make_call(name: str, raw_args: Any) -> Call:
    """Build a ``{"name", "arguments"}`` dict, coercing arguments to a dict."""
    if isinstance(raw_args, str):
        # OpenAI double-encodes function arguments as a JSON string.
        try:
            parsed = _json5.loads(raw_args)
        except _json5.JSON5Error:
            parsed = None
        raw_args = parsed
    if isinstance(raw_args, dict):
        return {"name": name, "arguments": raw_args}
    return {"name": name, "arguments": {}}


def _extract_calls(value: Any, strict: bool) -> Optional[List[Call]]:
    """Extract calls from a parsed JSON value.

    Returns ``None`` when *value* does not look like a tool call (or list of
    them) at all — this lets callers distinguish "no call here" from "an empty
    call". When *strict* is true, a bare ``{"name": ...}`` with no arguments key
    is rejected, which avoids mistaking ordinary data like ``{"name": "Bob",
    "age": 3}`` for a call.
    """
    if isinstance(value, list):
        out: List[Call] = []
        for item in value:
            got = _extract_calls(item, strict)
            if got is None:
                return None
            out.extend(got)
        return out or None

    if isinstance(value, dict):
        tool_calls = value.get("tool_calls")
        if isinstance(tool_calls, list):
            return _extract_calls(tool_calls, strict=False)

        function = value.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return [_make_call(function["name"], function.get("arguments"))]

        name = value.get("name")
        if isinstance(name, str):
            for key in _ARG_KEYS:
                if key in value:
                    return [_make_call(name, value[key])]
            if not strict:
                return [_make_call(name, {})]
            return None
        return None

    return None


# --------------------------------------------------------------------------- #
# Bracket / JSON span scanning in free text
# --------------------------------------------------------------------------- #
_OPEN_TO_CLOSE = {"{": "}", "[": "]"}


def _match_bracket(text: str, start: int) -> Optional[int]:
    """If ``text[start]`` opens a balanced ``{}``/``[]`` region, return the index
    just past its close, else ``None``. String contents (single or double
    quoted) and ``//`` / ``/* */`` comments are skipped so their brackets don't
    unbalance the count."""
    stack = [_OPEN_TO_CLOSE[text[start]]]
    i = start + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            quote = c
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c in "{[":
            stack.append(_OPEN_TO_CLOSE[c])
        elif c in "}]":
            if not stack or c != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return i + 1
        i += 1
    return None


def _iter_json_spans(text: str):
    """Yield ``(start, end)`` spans of top-level balanced JSON regions."""
    i = 0
    n = len(text)
    while i < n:
        if text[i] in "{[":
            end = _match_bracket(text, i)
            if end is not None:
                yield (i, end)
                i = end
                continue
        i += 1


# --------------------------------------------------------------------------- #
# Individual dialect parsers. Each returns (calls, spans-in-`text`).
# --------------------------------------------------------------------------- #

# Dialect 4: XML / DSML invoke blocks (fullwidth already normalized upstream).
# `_LT` matches a `<` optionally followed by a DeepSeek `|DSML|` marker.
_LT = r"<\s*(?:\|+\s*DSML\s*\|+\s*)?"
_INVOKE_OPEN = re.compile(_LT + r'invoke\s+name="([^"]+)"[^>]*?>')
_INVOKE_CLOSE = re.compile(_LT + r"/?\s*invoke\s*>")
_PARAM = re.compile(
    _LT + r'parameter\s+name="([^"]+)"[^>]*?>(.*?)' + _LT + r"/?\s*parameter\s*>",
    re.DOTALL,
)
_TOOLCALLS_WRAP = re.compile(_LT + r"/?\s*tool_calls\s*>", re.IGNORECASE)
_STRAY_DSML = re.compile(r"<\s*\|+\s*DSML\s*\|+[^>]*>")


def _coerce_param(value: str) -> Any:
    """XML/DSML parameter values are untyped text, so they are returned as
    strings — except a value that is itself a JSON object/array, which is
    parsed so nested structured parameters survive."""
    s = value.strip()
    if s[:1] in "{[":
        try:
            return _json5.loads(s)
        except _json5.JSON5Error:
            pass
    return s


def _parse_invoke(text: str) -> Tuple[List[Call], List[Span]]:
    opens = list(_INVOKE_OPEN.finditer(text))
    calls: List[Call] = []
    spans: List[Span] = []
    for idx, m in enumerate(opens):
        name = m.group(1)
        block_start = m.end()
        next_start = opens[idx + 1].start() if idx + 1 < len(opens) else len(text)
        close = _INVOKE_CLOSE.search(text, block_start, next_start)
        block_end = close.start() if close else next_start
        block = text[block_start:block_end]
        args: Dict[str, Any] = {}
        for pm in _PARAM.finditer(block):
            args[pm.group(1)] = _coerce_param(pm.group(2))
        calls.append({"name": name, "arguments": args})
        spans.append((m.start(), close.end() if close else block_end))
    return calls, spans


# Dialect 5: Hermes-style <tool_call>{...}</tool_call>.
_HERMES = re.compile(r"<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>", re.DOTALL)


def _parse_hermes(text: str) -> Tuple[List[Call], List[Span]]:
    calls: List[Call] = []
    spans: List[Span] = []
    for m in _HERMES.finditer(text):
        inner = m.group(1).strip()
        try:
            value = _json5.loads(inner)
        except _json5.JSON5Error:
            continue
        got = _extract_calls(value, strict=False)
        if got:
            calls.extend(got)
            spans.append((m.start(), m.end()))
    return calls, spans


# Dialects 1 & 3: bare (possibly dirty) JSON tool calls embedded in text.
def _parse_jsonscan(text: str) -> Tuple[List[Call], List[Span]]:
    calls: List[Call] = []
    spans: List[Span] = []
    for start, end in _iter_json_spans(text):
        segment = text[start:end]
        try:
            value = _json5.loads(segment)
        except _json5.JSON5Error:
            continue
        got = _extract_calls(value, strict=True)
        if got:
            calls.extend(got)
            spans.append((start, end))
    return calls, spans


# Dialect 2: fenced ```json ... ``` blocks (may wrap any of the above).
_FENCE = re.compile(r"```[^\n`]*\n?(.*?)```", re.DOTALL)


def _extract_any(text: str) -> List[Call]:
    for parser in (_parse_invoke, _parse_hermes, _parse_jsonscan):
        got, _ = parser(text)
        if got:
            return got
    return []


def _parse_fenced(text: str) -> Tuple[List[Call], List[Span]]:
    calls: List[Call] = []
    spans: List[Span] = []
    for m in _FENCE.finditer(text):
        got = _extract_any(m.group(1))
        if got:
            calls.extend(got)
            spans.append((m.start(), m.end()))
    return calls, spans


# --------------------------------------------------------------------------- #
# Detection: try parsers in ranked order, first non-empty wins.
# --------------------------------------------------------------------------- #
# Delimiter-scoped dialects (fenced / XML / Hermes) are tried before bare JSON
# so that `strip` removes the whole wrapper, not just the JSON inside it.
_PARSERS = (
    ("fenced", _parse_fenced),
    ("invoke", _parse_invoke),
    ("hermes", _parse_hermes),
    ("json", _parse_jsonscan),
)


def _detect(content: str) -> Tuple[str, List[Call], List[Span]]:
    norm = normalize_fullwidth(content)
    for name, parser in _PARSERS:
        calls, spans = parser(norm)
        if calls:
            return name, calls, spans
    return "", [], []


def _remove_spans(text: str, spans: List[Span]) -> str:
    out: List[str] = []
    last = 0
    for start, end in sorted(spans):
        if start < last:  # overlap guard
            continue
        out.append(text[last:start])
        last = end
    out.append(text[last:])
    return "".join(out)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def rescue(content: str) -> List[Call]:
    """Recover tool calls that leaked into ``content``.

    Returns a list of ``{"name": str, "arguments": dict}`` dicts, or ``[]`` when
    no tool call can be found. Dialects handled, tried in ranked order:

    1. Already-valid OpenAI ``tool_calls`` / function JSON embedded in text.
    2. Fenced code blocks (```` ```json ... ``` ````) wrapping a call.
    3. "Dirty" JSON — trailing commas, single quotes, ``//`` comments,
       unquoted keys.
    4. XML / DSML ``<invoke name="X"><parameter name="p">v</parameter></invoke>``,
       including DeepSeek's fullwidth-delimiter variant.
    5. Hermes-style ``<tool_call>{...}</tool_call>``.

    Multiple calls in one message are all returned.
    """
    if not content:
        return []
    return _detect(content)[1]


def rescue_first(content: str) -> Optional[Call]:
    """Return the first rescued call, or ``None`` if there is none."""
    calls = rescue(content)
    return calls[0] if calls else None


def strip(content: str) -> str:
    """Return ``content`` with the recovered tool-call markup removed.

    If no call is found, the content is returned unchanged.
    """
    if not content:
        return content
    name, _calls, spans = _detect(content)
    if not spans:
        return content
    if name == "invoke":
        # DSML markup may contain fullwidth chars; normalize first (1:1, so span
        # indices still align) then sweep up any leftover wrapper/marker tokens.
        work = normalize_fullwidth(content)
        out = _remove_spans(work, spans)
        out = _TOOLCALLS_WRAP.sub("", out)
        out = _STRAY_DSML.sub("", out)
    else:
        out = _remove_spans(content, spans)
    return _tidy(out)
