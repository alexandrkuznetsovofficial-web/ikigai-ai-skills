#!/usr/bin/env python3
"""Prepare an explicitly selected, immutable context snapshot. Dry-run unless --apply."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--dest', required=True)
    parser.add_argument('--file', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    raw_root, raw_dest = Path(args.source).expanduser(), Path(args.dest).expanduser()
    if raw_root.is_symlink() or raw_dest.is_symlink():
        raise ValueError('Symlink root is not allowed')
    root, dest = raw_root.resolve(), raw_dest.resolve()
    if not root.is_dir() or dest.exists() or root == dest or root in dest.parents:
        raise ValueError('Choose an existing source and a new snapshot outside the source')
    if not args.file or len(args.file) > 20:
        raise ValueError('Explicitly select 1..20 approved markdown files')
    selected, total = {}, 0
    for relative in args.file:
        pure = Path(relative)
        if pure.is_absolute() or '..' in pure.parts or any(part.startswith('.') for part in pure.parts):
            raise ValueError('Invalid source path')
        if any(part.lower() in ('personal', 'private', 'secrets', 'sessions') for part in pure.parts):
            raise ValueError('Private categories are not part of this context snapshot')
        source = root / pure
        current = root
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('Symlink is not allowed')
        if not source.is_file() or source.suffix != '.md' or not re.fullmatch(r'[A-Za-z0-9_-]+\.md', source.name):
            raise ValueError('Select plain markdown files with portable names')
        if source.name in selected:
            raise ValueError('Duplicate basename; create distinct reviewed summaries first')
        content = source.read_bytes()
        if len(content) > 12000:
            raise ValueError('Each file must fit 12000 bytes')
        total += len(content)
        if total > 32000:
            raise ValueError('Snapshot must fit 32000 bytes')
        content.decode('utf-8')
        selected[source.name] = content
    print(json.dumps({'mode': 'apply' if args.apply else 'plan', 'files': list(selected),
                      'bytes': total, 'secrets_scan': 'not_a_guarantee_review_before_transfer'}, ensure_ascii=False))
    if args.apply:
        dest.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, content in selected.items():
            with (dest/name).open('xb') as handle:
                handle.write(content)
        (dest/'approved.json').write_text(json.dumps({'version': 1, 'files': list(selected)}, indent=2)+'\n')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print('STOP: '+str(error), file=sys.stderr)
        raise SystemExit(1)
