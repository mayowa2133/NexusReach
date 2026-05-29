"""Verify production-only binary dependencies are available."""

from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    missing: list[str] = []
    for binary in ("pdflatex",):
        if shutil.which(binary) is None:
            missing.append(binary)

    if missing:
        print("Missing runtime dependencies: " + ", ".join(missing), file=sys.stderr)
        return 1

    result = subprocess.run(
        ["pdflatex", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode

    print(result.stdout.splitlines()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
