"""Shell display only; execution always uses the original argv list."""

from __future__ import annotations

import shlex


def render_command(argv: list[str]) -> dict[str, str]:
    return {
        "powershell": "& "
        + " ".join("'" + item.replace("'", "''") + "'" for item in argv),
        "posix": shlex.join(argv),
    }
