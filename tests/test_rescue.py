"""Offline test suite for toolcall-rescue. No network, no GPU."""

from __future__ import annotations

import pytest

from toolcall_rescue import rescue, rescue_first, strip

# --------------------------------------------------------------------------- #
# No call
# --------------------------------------------------------------------------- #


def test_no_call_plain_text():
    assert rescue("just some regular text, no tools here") == []


def test_no_call_empty():
    assert rescue("") == []
    assert rescue_first("") is None


def test_no_call_prose_with_braces():
    # Braces that are not JSON must not crash or produce a call.
    assert rescue("i was like {so happy} and then {sad}") == []


def test_data_json_is_not_a_call():
    # Bare JSON without a tool-call shape is data, not a call.
    assert rescue('the config is {"name": "Bob", "age": 3}') == []
    assert rescue('result: {"status": "ok", "count": 5}') == []


# --------------------------------------------------------------------------- #
# Dialect 1: OpenAI tool_calls / function JSON embedded in text
# --------------------------------------------------------------------------- #


def test_openai_tool_calls_wrapper_double_encoded_args():
    content = (
        'Sure, let me check. '
        '{"tool_calls": [{"id": "call_1", "type": "function", '
        '"function": {"name": "get_weather", '
        '"arguments": "{\\"city\\": \\"NYC\\"}"}}]}'
    )
    assert rescue(content) == [
        {"name": "get_weather", "arguments": {"city": "NYC"}}
    ]


def test_openai_function_object_dict_args():
    content = (
        '{"type": "function", "function": '
        '{"name": "search", "arguments": {"q": "cats", "limit": 3}}}'
    )
    assert rescue(content) == [
        {"name": "search", "arguments": {"q": "cats", "limit": 3}}
    ]


def test_plain_name_arguments_object():
    content = 'okay: {"name": "roll_dice", "arguments": {"sides": 20}}'
    assert rescue(content) == [
        {"name": "roll_dice", "arguments": {"sides": 20}}
    ]


# --------------------------------------------------------------------------- #
# Dialect 2: fenced code blocks
# --------------------------------------------------------------------------- #


def test_fenced_json_single_call():
    content = 'Here:\n```json\n{"name": "search", "arguments": {"q": "cats"}}\n```'
    assert rescue(content) == [{"name": "search", "arguments": {"q": "cats"}}]


def test_fenced_json_tool_calls_array():
    content = (
        "```json\n"
        '{"tool_calls": [{"function": {"name": "now", "arguments": {}}}]}\n'
        "```"
    )
    assert rescue(content) == [{"name": "now", "arguments": {}}]


def test_fenced_non_call_json_is_ignored():
    content = "```json\n{\"foo\": 1, \"bar\": 2}\n```"
    assert rescue(content) == []


# --------------------------------------------------------------------------- #
# Dialect 3: dirty JSON
# --------------------------------------------------------------------------- #


def test_dirty_json_single_quotes_and_trailing_comma():
    content = "{'name': 'add', 'arguments': {'a': 1, 'b': 2,}}"
    assert rescue(content) == [{"name": "add", "arguments": {"a": 1, "b": 2}}]


def test_dirty_json_unquoted_keys():
    content = '{name: "roll", arguments: {sides: 20, count: 2}}'
    assert rescue(content) == [
        {"name": "roll", "arguments": {"sides": 20, "count": 2}}
    ]


def test_dirty_json_with_comments():
    content = (
        "{\n"
        '  "name": "deploy",  // the tool\n'
        '  "arguments": {"env": "prod"} /* target */\n'
        "}"
    )
    assert rescue(content) == [{"name": "deploy", "arguments": {"env": "prod"}}]


# --------------------------------------------------------------------------- #
# Dialect 4: XML / DSML (incl. fullwidth delimiters)
# --------------------------------------------------------------------------- #


def test_clean_invoke_single_param():
    content = (
        '<invoke name="get_weather">'
        '<parameter name="city">Paris</parameter>'
        "</invoke>"
    )
    assert rescue(content) == [
        {"name": "get_weather", "arguments": {"city": "Paris"}}
    ]


def test_clean_invoke_multiple_params():
    content = (
        '<invoke name="book">'
        '<parameter name="city">Paris</parameter>'
        '<parameter name="nights">3</parameter>'
        "</invoke>"
    )
    # Untyped markup values stay as strings.
    assert rescue(content) == [
        {"name": "book", "arguments": {"city": "Paris", "nights": "3"}}
    ]


def test_invoke_nested_json_param_is_parsed():
    content = (
        '<invoke name="set_config">'
        '<parameter name="opts">{"retries": 2, "verbose": true}</parameter>'
        "</invoke>"
    )
    assert rescue(content) == [
        {"name": "set_config", "arguments": {"opts": {"retries": 2, "verbose": True}}}
    ]


def test_dsml_fullwidth_delimiters():
    # DeepSeek-style: fullwidth ｜ ＜ ＞ (U+FF5C / U+FF1C / U+FF1E).
    content = (
        "sure\n"
        "＜｜｜DSML｜｜tool_calls＞\n"
        "＜｜｜DSML｜｜invoke name=\"delete_role\"＞\n"
        "＜｜｜DSML｜｜parameter name=\"role_id\" string=\"true\"＞"
        "151084＜｜DSML｜parameter＞\n"
        "＜｜DSML｜invoke＞\n"
        "＜｜DSML｜tool_calls＞"
    )
    assert rescue(content) == [
        {"name": "delete_role", "arguments": {"role_id": "151084"}}
    ]


# --------------------------------------------------------------------------- #
# Dialect 5: Hermes
# --------------------------------------------------------------------------- #


def test_hermes_single():
    content = (
        'let me look\n'
        '<tool_call>{"name": "web_search", "arguments": {"query": "python"}}</tool_call>'
    )
    assert rescue(content) == [
        {"name": "web_search", "arguments": {"query": "python"}}
    ]


def test_hermes_name_only():
    content = '<tool_call>{"name": "ping"}</tool_call>'
    assert rescue(content) == [{"name": "ping", "arguments": {}}]


def test_hermes_malformed_but_recoverable():
    # trailing comma inside the Hermes payload
    content = '<tool_call>{"name": "add", "arguments": {"a": 1, "b": 2,},}</tool_call>'
    assert rescue(content) == [{"name": "add", "arguments": {"a": 1, "b": 2}}]


# --------------------------------------------------------------------------- #
# Dialect 6: multiple calls in one message
# --------------------------------------------------------------------------- #


def test_multiple_hermes_calls():
    content = (
        '<tool_call>{"name": "a", "arguments": {"x": 1}}</tool_call>\n'
        '<tool_call>{"name": "b", "arguments": {"y": 2}}</tool_call>'
    )
    assert rescue(content) == [
        {"name": "a", "arguments": {"x": 1}},
        {"name": "b", "arguments": {"y": 2}},
    ]


def test_multiple_invoke_calls():
    content = (
        '<invoke name="first"><parameter name="p">1</parameter></invoke>'
        '<invoke name="second"><parameter name="q">2</parameter></invoke>'
    )
    assert rescue(content) == [
        {"name": "first", "arguments": {"p": "1"}},
        {"name": "second", "arguments": {"q": "2"}},
    ]


def test_multiple_calls_in_json_array():
    content = (
        '[{"name": "a", "arguments": {}}, '
        '{"name": "b", "arguments": {"z": 9}}]'
    )
    assert rescue(content) == [
        {"name": "a", "arguments": {}},
        {"name": "b", "arguments": {"z": 9}},
    ]


# --------------------------------------------------------------------------- #
# rescue_first
# --------------------------------------------------------------------------- #


def test_rescue_first_returns_single():
    content = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
    assert rescue_first(content) == {"name": "x", "arguments": {}}


# --------------------------------------------------------------------------- #
# strip
# --------------------------------------------------------------------------- #


def test_strip_hermes_leaves_prose():
    content = (
        "let me check that for you\n"
        '<tool_call>{"name": "web_search", "arguments": {"query": "python"}}</tool_call>'
    )
    assert strip(content) == "let me check that for you"


def test_strip_fenced():
    content = 'ok\n```json\n{"name": "search", "arguments": {"q": "cats"}}\n```\ndone'
    assert strip(content) == "ok\n\ndone"


def test_strip_dsml_fullwidth():
    content = (
        "on it\n"
        "＜｜｜DSML｜｜invoke name=\"delete_role\"＞"
        "＜｜｜DSML｜｜parameter name=\"role_id\"＞"
        "151084＜｜DSML｜parameter＞"
        "＜｜DSML｜invoke＞"
    )
    assert strip(content) == "on it"


def test_strip_no_call_unchanged():
    content = "nothing to see here"
    assert strip(content) == content


def test_strip_bare_json_call():
    content = 'calling now {"name": "roll", "arguments": {"sides": 6}} ok'
    assert strip(content) == "calling now  ok".strip()


# --------------------------------------------------------------------------- #
# Return-shape invariants
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "content",
    [
        '<tool_call>{"name": "x", "arguments": {"a": 1}}</tool_call>',
        '{"name": "y", "arguments": {}}',
        '<invoke name="z"><parameter name="p">v</parameter></invoke>',
    ],
)
def test_shape_invariant(content):
    calls = rescue(content)
    assert isinstance(calls, list)
    for call in calls:
        assert set(call.keys()) == {"name", "arguments"}
        assert isinstance(call["name"], str)
        assert isinstance(call["arguments"], dict)
