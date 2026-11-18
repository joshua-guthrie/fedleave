"""Record exact installed Python versions, without local paths or credentials.

Run with the same interpreter that built the suite. The complete build inventory
also includes build tools; it is not a native-library or vendored-code SBOM.
"""

from __future__ import annotations

import argparse
import json
from importlib.metadata import distribution, distributions
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def resolved_packages(*, runtime_only: bool = False) -> dict[str, str]:
    if runtime_only:
        pending = [("fedleave", ""), ("fedleave", "gui")]
        visited: set[tuple[str, str]] = set()
        selected = {}
        while pending:
            name, extra = pending.pop()
            name = canonicalize_name(name)
            if (name, extra) in visited:
                continue
            visited.add((name, extra))
            package = distribution(name)
            selected[name] = package.version
            for text in package.requires or []:
                requirement = Requirement(text)
                if requirement.marker and not requirement.marker.evaluate({"extra": extra}):
                    continue
                pending.append((requirement.name, ""))
                pending.extend((requirement.name, requested) for requested in requirement.extras)
    else:
        selected = {canonicalize_name(item.metadata["Name"]): item.version for item in distributions()}
    # Require valid public package names and exact versions before producing input
    # for an advisory service. Never forward editable paths or direct-URL metadata.
    for name, version in selected.items():
        Version(version)
        Requirement(f"{name}=={version}")
    return dict(sorted(selected.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--runtime-only", action="store_true")
    args = parser.parse_args()
    packages = resolved_packages(runtime_only=args.runtime_only)
    args.output.write_text(
        json.dumps(
            {"schema": 1, "scope": "runtime+gui" if args.runtime_only else "build-environment", "packages": packages},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    args.requirements.write_text(
        "".join(f"{name}=={version}\n" for name, version in packages.items() if name != "fedleave"), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
