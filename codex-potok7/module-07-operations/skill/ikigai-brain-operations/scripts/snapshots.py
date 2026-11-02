#!/usr/bin/env python3
"""Local snapshots and staged restore. Unrun draft, Python 3.9+, stdlib only."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
import uuid
import zipfile

MAX_FILE = 20_000_000
MAX_TOTAL = 100_000_000
SUFFIXES = {'.md', '.txt', '.json', '.py', '.toml', '.yaml', '.yml', '.sh', '.ps1', '.service', '.timer', '.plist'}
EXCLUDE = {'.git', '.codex', '.claude', '.secrets', 'secrets', 'node_modules', '__pycache__', 'backups', 'codex-home'}
MANIFEST = '__snapshot_manifest.json'


def reject_links(path):
    path = Path(path).expanduser().absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink path is not allowed')
    return path.resolve()


def member_path(name):
    p = PurePosixPath(name)
    if not p.parts or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive member')
    return p


def snapshot(args):
    root, dest = reject_links(args.source), reject_links(args.dest)
    if not root.is_dir() or (args.operation == 'snapshot' and (not (root/'AGENTS.md').is_file() or not (root/'memory').is_dir())):
        raise ValueError('Select a brain workspace with AGENTS.md and memory/')
    if dest == root or root in dest.parents:
        raise ValueError('Backup directory must be outside the brain workspace')
    files, total = {}, 0
    roots = ['.'] if args.operation == 'inbox' else ['AGENTS.md', 'SYSTEM.md', 'TEAM.md', 'memory', '.agents/skills']
    for prefix in roots:
        origin = root/prefix
        if not origin.exists():
            continue
        candidates = [origin] if origin.is_file() else origin.rglob('*')
        for path in candidates:
            relative = path.relative_to(root)
            if any(part in EXCLUDE or part.startswith('.env') for part in relative.parts):
                continue
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
                raise ValueError('Symlink inside selected data')
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            size = path.stat().st_size
            if size > MAX_FILE:
                raise ValueError('Selected file exceeds size budget')
            total += size
            if total > MAX_TOTAL:
                raise ValueError('Snapshot exceeds size budget')
            content = path.read_bytes()
            files[relative.as_posix()] = content
    print(json.dumps({'mode': 'apply' if args.apply else 'plan', 'operation': args.operation,
                      'files': len(files), 'bytes': total, 'encrypted': False}))
    if not args.apply:
        return
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-'+uuid.uuid4().hex[:8]
    archive = dest/('brain-'+stamp+'.zip')
    manifest = {'version': 1, 'created_utc': stamp, 'kind': args.operation, 'files': {name: hashlib.sha256(body).hexdigest() for name,body in files.items()}}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    os.chmod(archive, 0o600)
    print(json.dumps({'created': archive.name, 'retention': 'no_automatic_deletion'}))


def restore(args):
    archive, dest = reject_links(args.archive), reject_links(args.staging)
    if not archive.is_file() or dest.exists():
        raise ValueError('Use an existing archive and a new, absent staging directory')
    files, total = {}, 0
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or MANIFEST not in names or len(names) > 10000:
            raise ValueError('Invalid archive inventory')
        meta = z.getinfo(MANIFEST)
        if meta.file_size > 2_000_000:
            raise ValueError('Manifest too large')
        manifest = json.loads(z.read(MANIFEST))
        expected = manifest.get('files')
        if manifest.get('version') != 1 or not isinstance(expected, dict) or set(names) != set(expected)|{MANIFEST}:
            raise ValueError('Archive and manifest differ')
        for info in infos:
            if info.filename == MANIFEST:
                continue
            member_path(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.file_size > MAX_FILE:
                raise ValueError('Unsupported archive entry')
            total += info.file_size
            if total > MAX_TOTAL:
                raise ValueError('Restore exceeds size budget')
            content = z.read(info.filename)
            if hashlib.sha256(content).hexdigest() != expected[info.filename]:
                raise ValueError('Checksum mismatch')
            files[info.filename] = content
    print(json.dumps({'mode': 'apply' if args.apply else 'plan', 'operation': 'restore-staging',
                      'files': len(files), 'bytes': total, 'live_workspace_modified': False}))
    if args.apply:
        dest.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, content in files.items():
            target = dest.joinpath(*member_path(name).parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open('xb') as handle:
                handle.write(content)
            os.chmod(target, 0o600)
        print('Staging restore prepared. Compare before any live replacement.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    s = sub.add_parser('snapshot')
    s.add_argument('--source', required=True)
    s.add_argument('--dest', required=True)
    s.add_argument('--apply', action='store_true')
    i = sub.add_parser('inbox')
    i.add_argument('--source', required=True)
    i.add_argument('--dest', required=True)
    i.add_argument('--apply', action='store_true')
    r = sub.add_parser('restore')
    r.add_argument('--archive', required=True)
    r.add_argument('--staging', required=True)
    r.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    (snapshot if args.operation in ('snapshot', 'inbox') else restore)(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        print('STOP: '+str(error), file=sys.stderr)
        raise SystemExit(1)
