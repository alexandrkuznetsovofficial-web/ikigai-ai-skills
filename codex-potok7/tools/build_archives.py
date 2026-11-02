#!/usr/bin/env python3
"""Create distributable student archives. This does not install or run any kit."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
DIST.mkdir(exist_ok=True)

def eligible(p):
    return p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'

for module in sorted(ROOT.glob('module-*')):
    if not module.is_dir():continue
    output=DIST/(module.name+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(module.rglob('*')):
            if eligible(p):archive.write(p,p.relative_to(module.parent).as_posix())

output=DIST/'potok7-codex-student-kits-0.2.0-draft.zip'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(ROOT.rglob('*')):
        if eligible(p) and DIST not in p.parents:
            archive.write(p,'codex-potok7/'+p.relative_to(ROOT).as_posix())
print('Archives:',len(list(DIST.glob('*.zip'))))
