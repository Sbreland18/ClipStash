#!/usr/bin/env python3
"""
The one place ClipStash's version number is written down.

Everything else reads it from here:
  * clipstash.py     shows it, and compares against the update feed
  * build.py         passes it to Inno Setup and stamps the update manifest
  * installer.iss    receives it as /DAppVersion rather than hardcoding it

Bump this, rebuild, publish. Nothing else needs editing.

Use plain dotted numbers - "1.2.0", "1.2.1". Comparison is numeric per part, so
"1.10.0" correctly sorts above "1.9.0", which a string comparison would get
backwards.
"""

__version__ = "1.2.0"


def parse(text: str) -> tuple:
    """Turn a version string into a sortable tuple, tolerating odd input."""
    parts = []
    for chunk in str(text).strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    # Pad so "1.2" and "1.2.0" compare equal rather than 1.2 sorting lower.
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str | None = None) -> bool:
    """
    Is `candidate` a later version than `current` (defaulting to this build)?

    The default is resolved here rather than in the signature on purpose. A
    default of `current: str = __version__` captures the value once, when the
    module is first imported, so it can never reflect a later change - which
    makes the function impossible to test against a different version and is a
    quiet trap for anyone who later makes the version dynamic.
    """
    return parse(candidate) > parse(current if current is not None else __version__)


if __name__ == "__main__":
    print(__version__)
