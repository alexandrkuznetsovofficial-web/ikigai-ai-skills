#!/usr/bin/env python3
"""Module 1: create missing files only; stdlib, Python 3.8+. Agent-side helper."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import sys

SKILL_NAME = 'ikigai-brain-architect'
MARKER = '.ikigai/module01.json'


def safe_path(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or '..' in parts or '\\' in relative:
        raise ValueError('Unsafe package path')
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlink is not allowed: ' + relative)
    if root not in current.resolve().parents:
        raise ValueError('Path leaves workspace')
    return current


def package_files(skill_root):
    files = {}
    template = skill_root / 'assets' / 'brain-template'
    for source in sorted(template.rglob('*')):
        if source.is_file():
            name = source.relative_to(template).as_posix()
            files['.gitignore' if name == 'gitignore.txt' else name] = source.read_text(encoding='utf-8')
    for source in sorted(skill_root.rglob('*')):
        if source.is_file() and '__pycache__' not in source.parts and source.suffix != '.pyc':
            files['.agents/skills/' + SKILL_NAME + '/' + source.relative_to(skill_root).as_posix()] = source.read_text(encoding='utf-8')
    return files


def apply_files(target, files, apply=False):
    target = Path(target).expanduser()
    if target.is_symlink() or not target.is_dir():
        raise ValueError('Target must be an existing normal working folder')
    root = target.resolve()
    destinations = {name: safe_path(root, name) for name in files}
    marker = safe_path(root, MARKER)
    known_install = marker.exists()
    if known_install:
        info = json.loads(marker.read_text(encoding='utf-8'))
        if info.get('module') != 'ikigai-codex-architecture' or info.get('version') != '0.1.0':
            raise ValueError('Unknown installation marker/version; review before continuing')
    elif any((root / name).exists() for name in ('AGENTS.md', 'CLAUDE.md', 'memory')):
        raise ValueError('Existing brain detected; choose a separate empty folder')
    # Validate all destinations and their parent types before any mutation.
    for name, dest in destinations.items():
        if dest.exists() and not dest.is_file():
            raise ValueError('File path is occupied by directory: ' + name)
        parent = dest.parent
        while parent != root:
            if parent.exists() and not parent.is_dir():
                raise ValueError('Parent path is not a directory: ' + name)
            parent = parent.parent
    if marker.exists() and not marker.is_file():
        raise ValueError('Invalid marker')
    planned = [name for name, dest in destinations.items() if not dest.exists()]
    kept = [name for name, dest in destinations.items() if dest.exists()]
    if apply:
        if not known_install:
            marker.parent.mkdir(parents=True, exist_ok=True)
            with marker.open('x', encoding='utf-8') as handle:
                json.dump({'module': 'ikigai-codex-architecture', 'version': '0.1.0',
                           'session_test': 'not_run', 'status': 'awaiting-practice'}, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
        for name in planned:
            dest = safe_path(root, name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation: never replace user data.
            with dest.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(files[name])
    return {'mode': 'apply' if apply else 'plan', 'created' if apply else 'would_create': planned,
            'preserved': kept, 'session_test': 'not_run' if not known_install else info.get('session_test', 'not_run')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    skill_root = Path(__file__).resolve().parents[1]
    print(json.dumps(apply_files(args.target, package_files(skill_root), args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
