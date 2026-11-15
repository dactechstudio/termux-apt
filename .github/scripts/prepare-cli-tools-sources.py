#!/usr/bin/env python3
"""Verify and vendor the pinned CLI and network tools package source closure for CI."""

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
        "apr-util",
        "apr-util-1.6.3.tar.gz",
        "https://archive.apache.org/dist/apr/apr-util-1.6.3.tar.gz",
        "2b74d8932703826862ca305b094eef2983c27b39d5c9414442e9976a9acf1983",
        "https://downloads.apache.org/apr/apr-util-${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "dnsutils",
        "bind-9.20.24.tar.xz",
        "https://downloads.isc.org/isc/bind9/9.20.24/bind-9.20.24.tar.xz",
        "989fef1fc88ea59d04cd86f854dca5a4616a20a9968bcdde3c1a3668ab36be08",
        '"https://downloads.isc.org/isc/bind9/${TERMUX_PKG_VERSION}/bind-${TERMUX_PKG_VERSION}.tar.xz"',
    ),
    Source(
        "nodejs-lts",
        "node-v24.17.0.tar.xz",
        "https://nodejs.org/dist/v24.17.0/node-v24.17.0.tar.xz",
        "a7ab562ed2369a29c68b72fa00e3103bcdfe37063dff799c6acc8e404e275fcd",
        "https://nodejs.org/dist/v${TERMUX_PKG_VERSION}/node-v${TERMUX_PKG_VERSION}.tar.xz",
    ),
    Source(
        "netcat-openbsd",
        "netcat-openbsd-debian-1.238-1.tar.gz",
        "https://salsa.debian.org/debian/netcat-openbsd/-/archive/debian/1.238-1/netcat-openbsd-debian-1.238-1.tar.gz",
        "ca2fed5e3e0e9841af812bd7ad2ed9e094f5c4cb72817e91323c75e14858af4a",
        '"https://salsa.debian.org/debian/netcat-openbsd/-/archive/debian/${TERMUX_PKG_VERSION}/netcat-openbsd-debian-${TERMUX_PKG_VERSION}.tar.gz"',
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


def patch_nodejs_lts(packages: Path) -> None:
    recipe = packages / "packages" / "nodejs-lts" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    contents = contents.replace(
        'TERMUX_PKG_RECOMMENDS="npm"',
        'TERMUX_PKG_PROVIDES="nodejs, npm"',
    )
    contents = contents.replace("\t\t--without-npm \\\n", "")
    old_debscripts = """termux_step_create_debscripts() {
\tcat <<- EOF > ./preinst
\t#!$TERMUX_PREFIX/bin/sh
\tif [ "\\$#" = "3" ] && dpkg --compare-versions "\\$2" le "24.13.0"; then
\t\techo "Starting with nodejs-lts v24.13.0-1, npm is no longer bundled with nodejs-lts package."
\t\techo "You might want to install npm package separately if you need it."
\t\techo "You can install it by running: pkg install npm"
\t\techo "It should not be needed unless you are using --no-install-recommends with apt."
\tfi
\tEOF
}"""
    if old_debscripts in contents:
        contents = contents.replace(old_debscripts, "", 1)
    recipe.write_text(contents, encoding="utf-8")


def patch_foot_checksum(packages: Path) -> None:
    recipe = packages / "x11-packages" / "foot" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    old_sha = "4e6131cc859ec6a36569f1978cf3617cc3836a681d13d228ded1b4885dab7770"
    new_sha = "f5917cad2d7b723b99873e53d78fd10ea202923d189aed5086591fc53b70b7e3"
    if old_sha in contents:
        contents = contents.replace(old_sha, new_sha, 1)
    elif new_sha not in contents:
        raise ValueError(f"Unexpected source checksum in {recipe}")
    recipe.write_text(contents, encoding="utf-8")


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
        patch_recipe(packages, source, source_dir.name)
        print(f"{source.package}: {source.sha256} {destination.name}")
    patch_nodejs_lts(packages)
    patch_foot_checksum(packages)


if __name__ == "__main__":
    main()
