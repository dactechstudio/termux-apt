#!/usr/bin/env python3
"""Create a signed APT repository from custom-prefix Termux .deb outputs."""

import argparse
import datetime
import gzip
import hashlib
import shutil
import subprocess
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', type=Path, help='Termux package build output directory')
    parser.add_argument('site', type=Path, help='Empty GitHub Pages staging directory')
    args = parser.parse_args()
    debs = sorted(args.packages.rglob('*.deb'))
    if not debs:
        raise SystemExit('No .deb packages found; refusing to publish an empty repository')
    if args.site.exists() and any(args.site.iterdir()):
        raise SystemExit('Repository staging directory must be empty')

    pool = args.site / 'pool/main'
    index_dir = args.site / 'dists/stable/main/binary-aarch64'
    invalid = []
    for package in debs:
        result = subprocess.run(
            ['dpkg-deb', '--field', str(package), 'Architecture'],
            text=True, capture_output=True,
        )
        if result.returncode:
            invalid.append(f'{package}: {result.stderr.strip()}')
            continue
        architecture = result.stdout.strip()
        if architecture not in {'aarch64', 'all'}:
            invalid.append(f'{package}: unexpected architecture {architecture}')
    if invalid:
        raise SystemExit('Invalid packages; refusing to publish:\n' + '\n'.join(invalid))

    pool.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    indexed_packages = 0
    for package in debs:
        digest = sha256_file(package)
        destination = pool / f'{digest}.deb'
        if destination.exists():
            if sha256_file(destination) != digest:
                raise SystemExit(f'SHA-256 collision while indexing {package}')
            continue
        shutil.copy2(package, destination)
        indexed_packages += 1

    result = subprocess.run(
        ['dpkg-scanpackages', '--multiversion', 'pool/main', '/dev/null'],
        cwd=args.site, text=True, capture_output=True, check=True,
    )
    packages = index_dir / 'Packages'
    packages.write_text(result.stdout, encoding='utf-8')
    if result.stdout.count('\nPackage: ') + result.stdout.startswith('Package: ') < indexed_packages:
        raise SystemExit('APT index omitted one or more built packages')
    compressed = index_dir / 'Packages.gz'
    with compressed.open('wb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as archive:
            archive.write(packages.read_bytes())

    release = args.site / 'dists/stable/Release'
    listed = [packages, compressed]
    lines = [
        'Origin: DAC Tech Studio',
        'Label: Termux custom ARM64 packages',
        'Suite: stable',
        'Codename: stable',
        'Architectures: aarch64',
        'Components: main',
        'Date: ' + datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000'),
        'SHA256:',
    ]
    for path in listed:
        relative = path.relative_to(args.site / 'dists/stable')
        lines.append(f' {hashlib.sha256(path.read_bytes()).hexdigest()} {path.stat().st_size} {relative}')
    release.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    subprocess.run([
        'gpg', '--batch', '--yes', '--digest-algo', 'SHA256', '--clearsign',
        '--output', str(release.parent / 'InRelease'), str(release),
    ], check=True)
    subprocess.run([
        'gpg', '--batch', '--yes', '--digest-algo', 'SHA256', '--detach-sign',
        '--output', str(release.parent / 'Release.gpg'), str(release),
    ], check=True)
    (args.site / '.nojekyll').touch()
    print(f'Published {indexed_packages} custom-prefix packages to {args.site}')


if __name__ == '__main__':
    main()
