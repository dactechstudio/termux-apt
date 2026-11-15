#!/usr/bin/env python3
"""Verify the custom-prefix ARM64 CLI tools package closure."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


OLD_PREFIX = b"/data/data/com.termux/files"
NEW_PREFIX = b"/data/data/com.dactechstudio.termux/files"
REQUIRED = {
    "git",
    "htop",
    "libsodium",
    "tmux",
    "vim",
    "wget",
    "xxd",
}
REQUIRED_BINARIES = {
    "git": "bin/git",
    "htop": "bin/htop",
    "tmux": "bin/tmux",
    "vim": "libexec/vim/vim",
    "wget": "bin/wget",
    "xxd": "bin/xxd",
}


def field(package: Path, name: str) -> str:
    return subprocess.check_output(
        ["dpkg-deb", "--field", str(package), name], text=True
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", type=Path)
    args = parser.parse_args()
    found: dict[str, Path] = {}
    for archive in sorted(args.packages.glob("*.deb")):
        name = field(archive, "Package")
        if name in REQUIRED:
            architecture = field(archive, "Architecture")
            if architecture not in {"aarch64", "all"}:
                raise ValueError(f"{name}: unexpected architecture {architecture}")
            found[name] = archive
    missing = REQUIRED - found.keys()
    if missing:
        raise ValueError("Missing CLI tools package closure: " + ", ".join(sorted(missing)))

    saw_new_prefix = False
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, archive in found.items():
            destination = root / name
            subprocess.run(
                ["dpkg-deb", "--extract", str(archive), str(destination)], check=True
            )
            for candidate in destination.rglob("*"):
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                data = candidate.read_bytes()
                if OLD_PREFIX in data:
                    raise ValueError(
                        f"Stock com.termux prefix remains in {name}:{candidate.relative_to(destination)}"
                    )
                saw_new_prefix = saw_new_prefix or NEW_PREFIX in data
            expected_bin = REQUIRED_BINARIES.get(name)
            if expected_bin is not None:
                binary = (
                    destination
                    / "data"
                    / "data"
                    / "com.dactechstudio.termux"
                    / "files"
                    / "usr"
                    / expected_bin
                )
                if not (binary.is_file() or binary.is_symlink()):
                    raise ValueError(
                        f"The {name} package does not contain {expected_bin} at the custom prefix"
                    )
    if not saw_new_prefix:
        raise ValueError("No custom application prefix found in the CLI tools package closure")
    print("Verified custom-prefix CLI tools package closure: " + ", ".join(sorted(found)))


if __name__ == "__main__":
    main()

