# toolcall-rescue

Salvage tool/function calls that a model leaked into `message.content` as XML, dirty JSON, Hermes tags, or fullwidth-unicode markup — turn them back into a normal `[{"name", "arguments"}]` list. Zero dependencies, no network, no model.

```python
from toolcall_rescue import rescue

rescue('<tool_call>{"name": "get_weather", "arguments": {"city": "NYC"}}</tool_call>')
# [{'name': 'get_weather', 'arguments': {'city': 'NYC'}}]
```

## What it does

The OpenAI chat API returns tool calls in a structured `tool_calls` field, and most SDKs read only that field. But plenty of models — local models behind llama.cpp, quantized fine-tunes, and some hosted models like DeepSeek — don't reliably fill it in, and the call arrives as text inside `message.content` instead. `toolcall-rescue` is a small salvage layer that recognizes the common leaked shapes and canonicalizes each one into `{"name": str, "arguments": dict}`. It is deliberately a fallback, not a framework: check your `tool_calls` field first, and reach for `rescue` only when it comes back empty.

## Why

When the structured field is empty, the tool call is usually still there — just stranded in the content string as one of several markup dialects:

- a Hermes/NousResearch `<tool_call>{...}</tool_call>` block,
- a Markdown ```` ```json ```` fenced block,
- "dirty" JSON (single quotes, trailing commas, `//` comments, unquoted keys),
- Anthropic-style `<invoke><parameter>` XML,
- or DeepSeek emitting that XML with **fullwidth** delimiters (`｜` `＜` `＞`, U+FF5C / U+FF1C / U+FF1E) instead of ASCII.

The SDK sees a plain string, so the tool never fires. This library exists to pull the call back out of that string, without adding a dependency or a network round-trip to do it.

## Install

```bash
git clone https://github.com/insomniac-asif/toolcall-rescue
cd toolcall-rescue
pip install .            # or: pip install -e ".[dev]" to run the tests
```

Python 3.8+. No third-party runtime dependencies; the optional `[dev]` extra pulls in `pytest`.

## Quickstart

The public surface is four functions, imported from the package root:

```python
from toolcall_rescue import rescue, strip

content = "let me check that\n" \
          '<tool_call>{"name": "web_search", "arguments": {"query": "python"}}</tool_call>'

rescue(content)   # -> [{'name': 'web_search', 'arguments': {'query': 'python'}}]
strip(content)    # -> 'let me check that'
```

`rescue(content)` returns `[]` cleanly when there is no call, so it drops in as a fallback after the normal path:

```python
calls = message.tool_calls or rescue(message.content or "")
```

- `rescue(content)` → list of `{name, arguments}` calls (possibly empty).
- `rescue_first(content)` → the first call, or `None`.
- `strip(content)` → the same text with the recovered tool-call markup removed.
- `normalize_fullwidth(text)` → the fullwidth→ASCII pass, exposed for reuse.

There is also a CLI entry point (`toolcall-rescue`) that reads from a file or stdin:

```bash
echo '<tool_call>{"name":"ping","arguments":{}}</tool_call>' | toolcall-rescue
# prints the recovered calls as indented JSON

toolcall-rescue --strip message.txt   # print the content with the markup removed
```

The CLI takes an optional file argument (defaults to stdin), a `--strip` flag, and `--indent` (default 2) for JSON output. A runnable walkthrough of every dialect lives in [`examples/demo.py`](examples/demo.py).

## How it works

1. **Normalize** fullwidth `｜＜＞` to ASCII `|<>`. The mapping is 1:1, so string indices are preserved — which is what lets `strip` later remove the exact markup span.
2. **Try each dialect parser in ranked order** and return the first non-empty result: fenced code block → XML/DSML `invoke` → Hermes `<tool_call>` → a bare JSON scan. Delimiter-scoped dialects run before the bare-JSON scan so `strip` removes the whole wrapper, not just the JSON inside it. The JSON scan walks the text for balanced `{...}`/`[...]` regions and parses each with a small built-in tolerant reader (`_json5.py`) that accepts single quotes, trailing commas, comments, and unquoted keys.
3. **Canonicalize** every recognized shape — OpenAI `tool_calls`, a bare `function` object, or a plain `{name, arguments}` — into `{"name": str, "arguments": dict}`. OpenAI's double-encoded `arguments` (a JSON string inside the JSON) is decoded back to a dict.
4. **Guard against false positives:** the bare-JSON scan requires a call-ish shape (a `name` plus an arguments key, or a `function`/`tool_calls` wrapper), so ordinary data like `{"name": "Bob", "age": 3}` is not treated as a call.

The package is four source files: `core.py` (the parsers and dispatch), `_json5.py` (the tolerant JSON reader), `cli.py`, and `__init__.py`.

## Status / limitations

Early (v0.1.0) but focused and tested — a fully offline pytest suite (`tests/test_rescue.py`, 32 tests covering each dialect plus multi-call, no-call, and malformed-but-recoverable cases) runs with no network, model, or GPU. Honest boundaries:

- **Inference servers increasingly parse these upstream.** vLLM, llama.cpp, Ollama and others ship tool-call parsers that will often populate `tool_calls` for you. This library is for the cases they miss — older/edge builds, unusual fine-tunes, or providers that leak markup into `content`.
- **XML/DSML parameter values are returned as strings** (the markup carries no type info), except a value that is itself a JSON object/array, which is parsed. `<parameter name="n">3</parameter>` yields `"3"`, not `3`.
- **Heuristic, not a grammar.** It targets the common real-world shapes above; deeply nested or exotic markup, or a call split across non-adjacent fragments, may not be recovered.
- **First dialect wins.** If one message genuinely mixes dialects, only the highest-ranked matching dialect's calls are returned.
- **No streaming.** `rescue` operates on a complete string, not partial chunks, and it does not reconstruct truncated or structurally broken JSON beyond the documented leniencies.

MIT licensed.

---

Part of a small set of agent-reliability / honesty tooling — libraries aimed at making LLM tool use and agent behavior more robust and less prone to silent failure.
