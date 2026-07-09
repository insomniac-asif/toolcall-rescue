"""Command-line interface for toolcall-rescue.

Read from a file or stdin, print rescued tool calls as JSON (default) or the
stripped content (``--strip``).

    echo '<tool_call>{"name":"ping","arguments":{}}</tool_call>' | toolcall-rescue
    toolcall-rescue message.txt
    toolcall-rescue --strip message.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .core import rescue, strip


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="toolcall-rescue",
        description="Salvage tool/function calls that leaked into LLM message content.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="File to read (defaults to stdin).",
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Print the content with tool-call markup removed instead of the calls.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent for rescued calls (default: 2).",
    )
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            content = fh.read()
    else:
        content = sys.stdin.read()

    if args.strip:
        sys.stdout.write(strip(content))
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        calls = rescue(content)
        print(json.dumps(calls, indent=args.indent, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
