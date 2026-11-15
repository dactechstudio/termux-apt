#!/usr/bin/env python3
"""Verify and vendor the pinned CLI tools package source closure for CI."""

from __future__ import annotations

import argparse
import hashlib
import tarfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    package: str
    filename: str
    url: str
    sha256: str
    recipe_url: str
    original_sha256: str | None = None


SOURCES = (
    Source(
        "c-ares",
        "c-ares-1.34.6.tar.gz",
        "https://github.com/c-ares/c-ares/archive/refs/tags/v1.34.6.tar.gz",
        "4358939ff800b13b92f37d5fdda003718101faedfbdee792d6b79ddc1a53d890",
        "https://github.com/c-ares/c-ares/archive/refs/tags/v$TERMUX_PKG_VERSION.tar.gz",
    ),
    Source(
        "libicu",
        "icu4c-78.3-sources.tgz",
        "https://github.com/unicode-org/icu/releases/download/release-78.3/icu4c-78.3-sources.tgz",
        "3a2e7a47604ba702f345878308e6fefeca612ee895cf4a5f222e7955fabfe0c0",
        "https://github.com/unicode-org/icu/releases/download/release-${TERMUX_PKG_VERSION}/icu4c-${TERMUX_PKG_VERSION}-sources.tgz",
    ),
    Source(
        "golang",
        "go1.26.4.src.tar.gz",
        "https://go.dev/dl/go1.26.4.src.tar.gz",
        "4f668a32fbfc1132e6a881fb968c2f1dada631492a339211735fbb255a42602d",
        "https://go.dev/dl/go${TERMUX_PKG_VERSION#*:}.src.tar.gz",
    ),
)


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def download(source: Source, destination: Path) -> None:
    if destination.is_file() and digest(destination) == source.sha256:
        return
    destination.unlink(missing_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                source.url,
                headers={"User-Agent": "DAC-Terminal-source-preflight/1.0"},
            )
            checksum = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    checksum.update(block)
                    output.write(block)
            actual = checksum.hexdigest()
            if actual != source.sha256:
                raise ValueError(f"{source.package}: expected {source.sha256}, got {actual}")
            temporary.replace(destination)
            return
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(attempt * 5)


def audit_archive(source: Source, archive_path: Path) -> None:
    if archive_path.suffix == ".xz":
        mode = "r:xz"
    elif archive_path.suffix == ".bz2":
        mode = "r:bz2"
    else:
        mode = "r:gz"
    with tarfile.open(archive_path, mode=mode) as archive:
        for member in archive:
            if not member.isfile():
                continue
            member_file = archive.extractfile(member)
            if member_file is None:
                continue
            if b"/data/data/com.termux/files" in member_file.read():
                raise ValueError(f"Unexpected stock prefix in {source.package}: {member.name}")


def patch_recipe(packages: Path, source: Source, source_dir_name: str) -> None:
    recipe = packages / "packages" / source.package / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    expected_url = f"TERMUX_PKG_SRCURL={source.recipe_url}"
    local_url = (
        "TERMUX_PKG_SRCURL=file://$TERMUX_SCRIPTDIR/"
        f"{source_dir_name}/{source.filename}"
    )
    if expected_url in contents:
        contents = contents.replace(expected_url, local_url, 1)
    elif local_url not in contents:
        raise ValueError(f"Unexpected source URL in {recipe}")

    if source.original_sha256 is not None:
        old_sha = f"TERMUX_PKG_SHA256={source.original_sha256}"
        new_sha = f"TERMUX_PKG_SHA256={source.sha256}"
        if old_sha in contents:
            contents = contents.replace(old_sha, new_sha, 1)
    expected_sha = f"TERMUX_PKG_SHA256={source.sha256}"
    if contents.count(expected_sha) != 1:
        raise ValueError(f"Unexpected source checksum in {recipe}")
    recipe.write_text(contents, encoding="utf-8")


def patch_libicu_license(packages: Path) -> None:
    recipe = packages / "packages" / "libicu" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    old = 'curl -L "https://raw.githubusercontent.com/unicode-org/icu/release-${TERMUX_PKG_VERSION//./-}/LICENSE" -o "$TERMUX_PKG_SRCDIR/LICENSE"'
    new = 'curl -fL "https://raw.githubusercontent.com/unicode-org/icu/release-${TERMUX_PKG_VERSION}/LICENSE" -o "$TERMUX_PKG_SRCDIR/LICENSE"'
    if old in contents:
        contents = contents.replace(old, new, 1)
        recipe.write_text(contents, encoding="utf-8")
    elif new not in contents:
        raise ValueError(f"Unexpected LICENSE URL in {recipe}")


def patch_golang(packages: Path) -> None:
    setup_script = packages / "scripts" / "build" / "setup" / "termux_setup_golang.sh"
    setup_contents = setup_script.read_text(encoding="utf-8")
    old_check = """\t\t# Need to be on latest go version to avoid risk of newer go version in go.mod
\t\t# leading to a prebuilt toolchain (which lacks the Termux patches):
\t\t(curl 'https://go.dev/VERSION?m=text' | grep -q $TERMUX_GO_VERSION) || termux_error_exit "Not on latest go version. Using $TERMUX_GO_VERSION"\n"""
    if old_check in setup_contents:
        setup_contents = setup_contents.replace(old_check, "", 1)
        setup_script.write_text(setup_contents, encoding="utf-8")

    exec_patch = packages / "packages" / "golang" / "src-os-exec_posix.go.patch"
    exec_contents = exec_patch.read_text(encoding="utf-8")
    exec_contents = exec_contents.replace(
        "/data/data/com.termux/files",
        "/data/data/com.dactechstudio.termux/files",
    )
    exec_patch.write_text(exec_contents, encoding="utf-8")

    recipe = packages / "packages" / "golang" / "build.sh"
    recipe_contents = recipe.read_text(encoding="utf-8")
    recipe_contents = recipe_contents.replace(
        'TERMUX_PKG_DEPENDS="clang"\nTERMUX_PKG_ANTI_BUILD_DEPENDS="clang"\nTERMUX_PKG_RECOMMENDS="resolv-conf"',
        'TERMUX_PKG_DEPENDS="resolv-conf"\nTERMUX_PKG_SUGGESTS="clang"',
    )
    recipe.write_text(recipe_contents, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", type=Path, help="Pinned termux-packages checkout")
    args = parser.parse_args()
    packages = args.packages.resolve()
    source_dir = packages / "verified-cli-sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        destination = source_dir / source.filename
        download(source, destination)
        audit_archive(source, destination)
        patch_recipe(packages, source, source_dir.name)
        print(f"{source.package}: {source.sha256} {destination.name}")
    patch_libicu_license(packages)
    patch_golang(packages)


if __name__ == "__main__":
    main()
