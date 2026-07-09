"""toolcall-rescue: salvage tool calls from messy LLM output.

    >>> from toolcall_rescue import rescue, strip
    >>> rescue('<tool_call>{"name": "ping", "arguments": {}}</tool_call>')
    [{'name': 'ping', 'arguments': {}}]
"""

from __future__ import annotations

from .core import normalize_fullwidth, rescue, rescue_first, strip

__all__ = ["rescue", "rescue_first", "strip", "normalize_fullwidth"]
__version__ = "0.1.0"
