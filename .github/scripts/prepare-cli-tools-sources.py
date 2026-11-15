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
        "termux-api",
        "termux-api-0.59.1.tar.gz",
        "https://github.com/termux/termux-api-package/archive/v0.59.1.tar.gz",
        "92c2da07991a0191735539428aabb793e0ddb8e33baac305bcf38d77aa1eda80",
        "https://github.com/termux/termux-api-package/archive/v${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "zip",
        "zip30.tar.gz",
        "https://downloads.sourceforge.net/infozip/zip30.tar.gz",
        "f0e8bb1f9b7eb0b01285495a2699df3a4b766784c1765a8f1aeedf63c0806369",
        '"https://downloads.sourceforge.net/infozip/zip${TERMUX_PKG_VERSION/.}.tar.gz"',
    ),
    Source(
        "oniguruma",
        "onig-6.9.10.tar.gz",
        "https://github.com/kkos/oniguruma/releases/download/v6.9.10/onig-6.9.10.tar.gz",
        "2a5cfc5ae259e4e97f86b68dfffc152cdaffe94e2060b770cb827238d769fc05",
        "https://github.com/kkos/oniguruma/releases/download/v$TERMUX_PKG_VERSION/onig-$TERMUX_PKG_VERSION.tar.gz",
    ),
    Source(
        "jq",
        "jq-1.8.2.tar.gz",
        "https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-1.8.2.tar.gz",
        "71b8d6e8f5fe81f6c6d0d110e3892251f6ce76ed095abd315e26e6e1193af3af",
        "https://github.com/jqlang/jq/releases/download/jq-$TERMUX_PKG_VERSION/jq-$TERMUX_PKG_VERSION.tar.gz",
    ),
    Source(
        "tree",
        "unix-tree-2.3.2.tar.gz",
        "https://gitlab.com/OldManProgrammer/unix-tree/-/archive/2.3.2/unix-tree-2.3.2.tar.gz",
        "513a53cbc42ca1f4ea06af2bab1f5283524a3848266b1d162416f8033afc4985",
        '"https://gitlab.com/OldManProgrammer/unix-tree/-/archive/${TERMUX_PKG_VERSION}/unix-tree-${TERMUX_PKG_VERSION}.tar.gz"',
    ),
    Source(
        "liblz4",
        "lz4-1.10.0.tar.gz",
        "https://github.com/lz4/lz4/archive/refs/tags/v1.10.0.tar.gz",
        "537512904744b35e232912055ccf8ec66d768639ff3abe5788d90d792ec5f48b",
        "https://github.com/lz4/lz4/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "libpopt",
        "popt-1.19.tar.gz",
        "http://ftp.rpm.org/popt/releases/popt-1.x/popt-1.19.tar.gz",
        "c25a4838fc8e4c1c8aacb8bd620edb3084a3d63bf8987fdad3ca2758c63240f9",
        "http://ftp.rpm.org/popt/releases/popt-1.x/popt-${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "zstd",
        "zstd-1.5.7.tar.gz",
        "https://github.com/facebook/zstd/archive/refs/tags/v1.5.7.tar.gz",
        "37d7284556b20954e56e1ca85b80226768902e2edabd3b649e9e72c0c9012ee3",
        "https://github.com/facebook/zstd/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "rsync",
        "rsync-3.4.4.tar.gz",
        "https://rsync.samba.org/ftp/rsync/src/rsync-3.4.4.tar.gz",
        "bd88cf82fa653da32314fb229136407c5c90f80d1758d8f4b091767877d8fa96",
        '"https://rsync.samba.org/ftp/rsync/src/rsync-${TERMUX_PKG_VERSION}.tar.gz"',
    ),
    Source(
        "libpcap",
        "libpcap-1.10.5.tar.xz",
        "https://deb.debian.org/debian/pool/main/libp/libpcap/libpcap_1.10.5.orig.tar.xz",
        "84fa89ac6d303028c1c5b754abff77224f45eca0a94eb1a34ff0aa9ceece3925",
        "https://fossies.org/linux/misc/libpcap-${TERMUX_PKG_VERSION}.tar.xz",
    ),
    Source(
        "lua54",
        "lua-5.4.8.tar.gz",
        "https://www.lua.org/ftp/lua-5.4.8.tar.gz",
        "4f18ddae154e793e46eeab727c59ef1c0c0c2b744e7b94219710d76f530629ae",
        "https://www.lua.org/ftp/lua-${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "nmap",
        "nmap-7.99.tar.bz2",
        "https://nmap.org/dist/nmap-7.99.tar.bz2",
        "df512492ffd108e53a27a06f26d8635bbe89e0e569455dc8ffef058c035d51b2",
        "https://nmap.org/dist/nmap-${TERMUX_PKG_VERSION}.tar.bz2",
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
    if source.package == "termux-api":
        return
    if archive_path.suffix == ".lz":
        data = archive_path.read_bytes()
        if b"/data/data/com.termux/files" in data:
            raise ValueError(f"Unexpected stock prefix in {source.package}")
        return
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


def patch_termux_api(packages: Path) -> None:
    patch_file = packages / "packages" / "termux-api" / "termux-api.c.patch"
    patch_contents = patch_file.read_text(encoding="utf-8")
    patch_contents = patch_contents.replace(
        '+    child_argv[5] = "com.termux/com.termux.app.TermuxService";',
        '+    child_argv[5] = "com.dactechstudio.termux/com.dactechstudio.termux.app.TermuxService";',
    )
    patch_contents = patch_contents.replace(
        '+    child_argv[13] = "com.termux.service_api";',
        '+    child_argv[13] = "com.dactechstudio.termux.service_api";',
    )
    patch_file.write_text(patch_contents, encoding="utf-8")

    recipe = packages / "packages" / "termux-api" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    hook = """
termux_step_pre_configure() {
\tsed -i 's/com\\.termux\\.api/com.dactechstudio.termux.api/g; s/com\\.termux/com.dactechstudio.termux/g' \\
\t\ttermux-api.c termux-api-broadcast.c scripts/termux-api-start.in scripts/termux-api-stop.in
}
"""
    if "termux_step_pre_configure()" not in contents:
        contents = contents.rstrip() + "\n" + hook
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
        audit_archive(source, destination)
        patch_recipe(packages, source, source_dir.name)
        print(f"{source.package}: {source.sha256} {destination.name}")
    patch_termux_api(packages)


if __name__ == "__main__":
    main()
