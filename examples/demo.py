"""Runnable demo: python examples/demo.py

Feeds one sample per dialect through rescue() and strip().
"""

from __future__ import annotations

from toolcall_rescue import rescue, strip

SAMPLES = {
    "openai json (embedded)": (
        'sure! {"tool_calls": [{"type": "function", "function": '
        '{"name": "get_weather", "arguments": "{\\"city\\": \\"Tokyo\\"}"}}]}'
    ),
    "fenced json": (
        "on it:\n```json\n"
        '{"name": "search", "arguments": {"q": "best ramen"}}\n```'
    ),
    "dirty json": "{name: 'roll', arguments: {sides: 20,}}  // go",
    "hermes tag": '<tool_call>{"name": "ping", "arguments": {}}</tool_call>',
    "xml invoke": (
        '<invoke name="book"><parameter name="city">Paris</parameter>'
        '<parameter name="nights">3</parameter></invoke>'
    ),
    "dsml fullwidth": (
        "＜｜｜DSML｜｜invoke name=\"delete_role\"＞"
        "＜｜｜DSML｜｜parameter name=\"role_id\"＞151084"
        "＜｜DSML｜parameter＞＜｜DSML｜invoke＞"
    ),
    "no call": "nothing to call here, just chatting",
}


def main() -> None:
    for label, content in SAMPLES.items():
        print(f"=== {label} ===")
        print("  rescue:", rescue(content))
        print("  strip :", repr(strip(content)))
        print()


if __name__ == "__main__":
    main()
