"""Path globbing where ``*`` stops at a separator and ``**`` does not."""

import re
from functools import lru_cache

_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|\[[^\]]*\]|[^*?\[]+")


@lru_cache(maxsize=None)
def compile_glob(pattern: str) -> re.Pattern:
    out = ["(?s)\\A"]
    for tok in _TOKEN.findall(pattern):
        if tok == "**/":
            # Match any number of leading directories, including none.
            out.append("(?:[^/]+/)*")
        elif tok == "**":
            out.append(".*")
        elif tok == "*":
            out.append("[^/]*")
        elif tok == "?":
            out.append("[^/]")
        elif tok.startswith("["):
            body = tok[1:-1]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append(f"[{body}]")
        else:
            out.append(re.escape(tok))
    out.append("\\Z")
    return re.compile("".join(out))


def matches(pattern: str, path: str) -> bool:
    """Report whether path matches pattern.

    A pattern ending in ``/**`` also matches the directory itself, so
    ``product/app/Foo/**`` covers ``product/app/Foo``.
    """
    if compile_glob(pattern).match(path):
        return True
    if pattern.endswith("/**"):
        return compile_glob(pattern[:-3]).match(path) is not None
    return False
