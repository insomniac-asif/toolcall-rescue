# Contributing to toolcall-rescue

Thanks! `toolcall-rescue` salvages tool calls from messy LLM output. It's a tiny,
zero-dependency library — please keep it that way.

## Dev setup

```bash
git clone https://github.com/insomniac-asif/toolcall-rescue
cd toolcall-rescue
pip install -e ".[dev]"
python -m pytest -q      # offline, no dependencies
```

## Adding a dialect (the main extension point)

Models emit tool calls in endless mangled shapes. To teach the parser a new one:

1. Write a parser function that takes the raw `content` string and returns
   `(calls, spans)` — the list of `{name, arguments}` plus the character spans they
   occupied (so `strip()` can remove them precisely).
2. Register it in `_PARSERS` in `core.py`, in priority order.
3. Add fixtures to `tests/` — at least one clean case, one multi-call case, and one
   malformed-but-recoverable case.

Real model outputs make the best fixtures — if you hit a shape it can't parse, open an
issue with the raw string and it becomes a test.

## The bar

- Zero third-party dependencies in the library.
- Tests stay green and offline.
- Don't over-match: a parser must not mistake ordinary JSON *data* for a tool call.
