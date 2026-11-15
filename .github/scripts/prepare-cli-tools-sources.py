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
        "wget",
        "wget-1.25.0.tar.lz",
        "https://mirrors.kernel.org/gnu/wget/wget-1.25.0.tar.lz",
        "19225cc756b0a088fc81148dc6a40a0c8f329af7fd8483f1c7b2fe50f4e08a1f",
        "https://mirrors.kernel.org/gnu/wget/wget-${TERMUX_PKG_VERSION}.tar.lz",
    ),
    Source(
        "htop",
        "htop-3.5.1.tar.gz",
        "https://github.com/htop-dev/htop/archive/refs/tags/3.5.1/htop-3.5.1.tar.gz",
        "dfc4a09845e9bc86f466a722e62b8f87d59028ff39689077ff2257a6a605061d",
        "https://github.com/htop-dev/htop/archive/refs/tags/${TERMUX_PKG_VERSION}/htop-${TERMUX_PKG_VERSION}.tar.gz",
    ),
    Source(
        "tmux",
        "tmux-3.6b.tar.gz",
        "https://github.com/tmux/tmux/archive/refs/tags/3.6b.tar.gz",
        "e71f6a6b87621c1a93b39f7e04e62caac61b4455e5f4cb3ffd1042536b8c47c5",
        "https://github.com/tmux/tmux/archive/refs/tags/${TERMUX_PKG_VERSION}.tar.gz",
        original_sha256="648510fc46bb32974368793445881c1cd254e4a8ec44e63ee4bc85bbb5af7081",
    ),
    Source(
        "git",
        "git-2.54.0.tar.xz",
        "https://mirrors.kernel.org/pub/software/scm/git/git-2.54.0.tar.xz",
        "f689162364c10de79ef89aa8dbf48731eb057e34edbbd20aca510ce0154681a3",
        "https://mirrors.kernel.org/pub/software/scm/git/git-${TERMUX_PKG_VERSION}.tar.xz",
    ),
    Source(
        "libsodium",
        "libsodium-1.0.22-RELEASE.tar.gz",
        "https://github.com/jedisct1/libsodium/archive/refs/tags/1.0.22-RELEASE.tar.gz",
        "5838bb0c3da6148c24ebe531d1ed1297de9a87aea77d426bcd99f289e681631c",
        '"https://github.com/jedisct1/libsodium/archive/refs/tags/${TERMUX_PKG_VERSION}-RELEASE.tar.gz"',
    ),
    Source(
        "vim",
        "vim-9.2.0650.tar.gz",
        "https://github.com/vim/vim/archive/refs/tags/v9.2.0650.tar.gz",
        "de9be55e39f7da67b3871974952d7cf61bab9d362434d9ff22d46fb2855a6dac",
        '"https://github.com/vim/vim/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz"',
    ),
)

TMUX_COMPLETION = Source(
    "tmux-completion",
    "tmux-bash-completion",
    "https://raw.githubusercontent.com/imomaliev/tmux-bash-completion/homebrew_1.0.0/completions/tmux",
    "05e79fc1ecb27637dc9d6a52c315b8f207cf010cdcee9928805525076c9020ae",
    "https://raw.githubusercontent.com/imomaliev/tmux-bash-completion/homebrew_1.0.0/completions/tmux",
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
    if archive_path.suffix == ".lz":
        data = archive_path.read_bytes()
        if b"/data/data/com.termux/files" in data:
            raise ValueError(f"Unexpected stock prefix in {source.package}")
        return
    mode = "r:xz" if archive_path.suffix == ".xz" else "r:gz"
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


def patch_tmux_completion(packages: Path, source_dir_name: str) -> None:
    recipe = packages / "packages" / "tmux" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    old_url = TMUX_COMPLETION.recipe_url
    new_url = f"file://$TERMUX_SCRIPTDIR/{source_dir_name}/{TMUX_COMPLETION.filename}"
    if old_url in contents:
        contents = contents.replace(old_url, new_url, 1)
    elif new_url not in contents:
        raise ValueError(f"Unexpected completion URL in {recipe}")
    recipe.write_text(contents, encoding="utf-8")


def patch_git_manpages(packages: Path) -> None:
    recipe = packages / "packages" / "git" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    old_block = """\t# Installing man requires asciidoc and xmlto, so git uses separate make targets for man pages
\tmake -j "$TERMUX_PKG_MAKE_PROCESSES" install-man

\tmake -j "$TERMUX_PKG_MAKE_PROCESSES" -C contrib/subtree $TERMUX_PKG_EXTRA_MAKE_ARGS
\tmake -C contrib/subtree $TERMUX_PKG_EXTRA_MAKE_ARGS "${TERMUX_PKG_MAKE_INSTALL_TARGET}"
\tmake -j "$TERMUX_PKG_MAKE_PROCESSES" -C contrib/subtree install-man"""
    new_block = """\tmake -j "$TERMUX_PKG_MAKE_PROCESSES" -C contrib/subtree $TERMUX_PKG_EXTRA_MAKE_ARGS
\tmake -C contrib/subtree $TERMUX_PKG_EXTRA_MAKE_ARGS "${TERMUX_PKG_MAKE_INSTALL_TARGET}" """
    if old_block in contents:
        contents = contents.replace(old_block, new_block, 1)
        recipe.write_text(contents, encoding="utf-8")
    elif new_block not in contents:
        raise ValueError(f"Unexpected install-man block in {recipe}")

    subpkg = packages / "packages" / "git" / "git-svn.subpackage.sh"
    subpkg_contents = subpkg.read_text(encoding="utf-8")
    subpkg_contents = subpkg_contents.replace('TERMUX_SUBPKG_DEPENDS="subversion-perl"\n', "")
    subpkg_contents = subpkg_contents.replace("share/man/man1/git-svn*\n", "")
    subpkg.write_text(subpkg_contents, encoding="utf-8")


def patch_vim_interpreters(packages: Path) -> None:
    recipe = packages / "packages" / "vim" / "build.sh"
    contents = recipe.read_text(encoding="utf-8")
    contents = contents.replace(
        'TERMUX_PKG_BUILD_DEPENDS="luajit, perl, python, ruby, tcl"',
        'TERMUX_PKG_BUILD_DEPENDS="python"',
    )
    contents = contents.replace(
        'TERMUX_PKG_SUGGESTS="luajit, perl, python, ruby, tcl"',
        'TERMUX_PKG_SUGGESTS="python"',
    )
    old_interp = """--enable-luainterp=dynamic
--with-lua-prefix=$TERMUX_PREFIX
--with-luajit
--enable-perlinterp=dynamic
--with-xsubpp=$TERMUX_PREFIX/bin/xsubpp
--enable-rubyinterp=dynamic
--enable-tclinterp=dynamic
"""
    if old_interp in contents:
        contents = contents.replace(old_interp, "", 1)
    old_patch = """\t# Vim doesn't support cross-compilation for Perl, Ruby and Tcl
\t# out of the box, so we need to patch the configure script to make it work.
\tlocal perl_version ruby_major_version tcl_major_version
\tperl_version="$(. "$TERMUX_SCRIPTDIR/packages/perl/build.sh"; echo "${TERMUX_PKG_VERSION[0]}")"
\truby_major_version="$(. "$TERMUX_SCRIPTDIR/packages/ruby/build.sh"; echo "${TERMUX_PKG_VERSION%\\.*}")"
\ttcl_major_version="$(. "$TERMUX_SCRIPTDIR/packages/tcl/build.sh"; echo "${TERMUX_PKG_VERSION%\\.*}")"

\tpatch="$TERMUX_PKG_BUILDER_DIR/configure-perl-ruby-tcl-cross-compiling.diff"
\techo "Applying patch: $(basename "$patch")"
\ttest -f "$patch" && sed \\
\t\t-e "s%\\@PERL_VERSION\\@%${perl_version}%g" \\
\t\t-e "s%\\@RUBY_MAJOR_VERSION\\@%${ruby_major_version}%g" \\
\t\t-e "s%\\@TCL_MAJOR_VERSION\\@%${tcl_major_version}%g" \\
\t\t-e "s%\\@PERL_PLATFORM\\@%${TERMUX_ARCH}-android%g" \\
\t\t-e "s%\\@RUBY_PLATFORM\\@%${TERMUX_HOST_PLATFORM}%g" \\
\t\t-e "s%\\@TERMUX_PREFIX\\@%${TERMUX_PREFIX}%g" \\
\t\t"$patch" | patch --silent -p1"""
    if old_patch in contents:
        contents = contents.replace(old_patch, "", 1)
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
    completion_dest = source_dir / TMUX_COMPLETION.filename
    download(TMUX_COMPLETION, completion_dest)
    patch_tmux_completion(packages, source_dir.name)
    patch_git_manpages(packages)
    patch_vim_interpreters(packages)


if __name__ == "__main__":
    main()

