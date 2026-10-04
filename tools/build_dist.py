#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка публикуемых копий репозитория скиллов из одного источника (kit 2.0).

Запуск из корня репозитория:
    python3 tools/build_dist.py                 # Mac / Linux
    py -3 tools/build_dist.py                   # Windows
    python3 tools/build_dist.py --allow-dirty   # локальная проба, НЕ для публикации

Что делает:
  0. Рабочее дерево должно быть чистым (git status пуст): публикуется только то, что
     закоммичено. Грязное дерево — стоп. --allow-dirty — только для локальной пробы:
     в сборку попадают и новые файлы, не закоммиченные, манифест помечается
     source_dirty / local_trial, рядом кладётся DO_NOT_PUBLISH.txt.
     Затем запускает tools/check_kit.py. Есть ошибки — сборка останавливается.
  1. dist/site/ — дерево для витрины Академии (/aipotok/skills/) с теми же
     относительными путями, что в репозитории. Состав — из git ls-files
     (файлы из .gitignore не попадают никогда), без папок dist/ и tools/ на любом
     уровне (тот же список, что в check_kit.py), скрытых файлов, *.bak* и без
     NOT_PUBLISHED_PREFIXES (brain-link/ci/, brain-link/tests/ — ни на витрину, ни в пак).
  2. dist/AI_Potok_Graduation_Pack_v2.zip — выпускной пак (имена в UTF-8,
     все файлы внутри папки AI_Potok_Graduation_Pack_v2/).
  3. dist/manifest.json — sha256 каждого файла витрины и пака + sha256 архива.
  4. Сверяет контрольные суммы: репозиторий = витрина = архив. Расхождение — стоп.

Папка dist/ в .gitignore: в git она не попадает.
Python 3.8+, без внешних зависимостей.
"""
from __future__ import print_function

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_kit import SKIP_DIRS, list_kit_files  # noqa: E402  единый список файлов и исключений

PACK_NAME = "AI_Potok_Graduation_Pack_v2"

# Состав выпускного пака: папки целиком или отдельные файлы (пути от корня репозитория).
PACK_ITEMS = [
    "second-brain-audit/",
    "novoselie-server-kit/audit/audit.sh",
    "novoselie-server-kit/audit/audit.ps1",
    "novoselie-server-kit/audit/START_HERE.txt",
    "novoselie-server-kit/audit/README.md",
    "memory-upgrade/",
    "memory-garden/",
    "weekly-distill/",
    "meeting-1/morning-brief.md",
    "SETUP_MORNING_BRIEF.md",
    "meeting-2-3/auto-commit-backup.md",
    "meeting-2-3/orchestrator.md",
    "project-splitter/",
    "ikigai-preflight/",
    "novoselie-server-kit/audit/skills/",
    "novoselie-server-kit/audit/docs/",
    "novoselie-server-kit/audit/MASTER_PROMPT.txt",
    "craft-to-skill/",
    "agents/",
    "templates/",
    "KIT_CONVENTIONS.md",
    "GRADUATION_PACK.md",
    "graduation/ikigai-graduation.md",
    "brain-link/",
]

# Не публикуются НИ на витрину, НИ в пак (префиксы путей от корня): тесты и CI-лаборатория нужны
# разработчику, не участнику (brain-link/ci/README.md обещает, что ci/ в дистрибутив не входит).
NOT_PUBLISHED_PREFIXES = [
    "brain-link/ci/",
    "brain-link/tests/",
]

# Внутри папок пака дополнительно не берём (префиксы путей).
PACK_EXCLUDE = list(NOT_PUBLISHED_PREFIXES)

# Не публикуется ни на витрину, ни в пак. Папки — SKIP_DIRS из check_kit.py
# (dist, tools, .git, __pycache__, node_modules) на любом уровне пути.
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# Фиксированная дата внутри архива: одинаковые файлы дают одинаковый архив.
ZIP_DATE = (2026, 10, 1, 0, 0, 0)


def die(msg):
    print("✗ " + msg)
    sys.exit(1)


def is_excluded(relpath):
    if any(relpath.startswith(p) for p in NOT_PUBLISHED_PREFIXES):
        return True
    parts = relpath.split("/")
    for p in parts:
        if p in SKIP_DIRS or p in EXCLUDE_FILES:
            return True
        if p.startswith("."):  # .git, .gitignore, .gitattributes, скрытые файлы
            return True
        if ".bak" in p.lower():
            return True
    return False


def repo_files(root, allow_dirty):
    """Чистое дерево: только файлы из git (в индексе). Проба: ещё и новые, не из .gitignore."""
    return [rp for rp in list_kit_files(root, tracked_only=not allow_dirty)
            if not is_excluded(rp)]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_check(root):
    script = os.path.join(root, "tools", "check_kit.py")
    print("→ check_kit.py")
    code = subprocess.call([sys.executable, script, "--root", root])
    if code != 0:
        die("check_kit.py нашёл ошибки — сборка остановлена. Исправьте и запустите снова.")


def safe_reset(root, path):
    """Удаляет только то, что лежит внутри dist/ этого репозитория."""
    dist = os.path.realpath(os.path.join(root, "dist"))
    real = os.path.realpath(path)
    if real != dist and not real.startswith(dist + os.sep):
        die("отказ удалять вне dist/: %s" % path)
    if os.path.isdir(real):
        shutil.rmtree(real)
    elif os.path.exists(real):
        os.remove(real)


def build_site(root, files):
    site = os.path.join(root, "dist", "site")
    safe_reset(root, site)
    for rp in files:
        dst = os.path.join(site, *rp.split("/"))
        d = os.path.dirname(dst)
        if not os.path.isdir(d):
            os.makedirs(d)
        shutil.copy2(os.path.join(root, *rp.split("/")), dst)
    return site


def pack_files(root, files):
    chosen, missing = [], []
    for item in PACK_ITEMS:
        if item.endswith("/"):
            sub = [f for f in files if f.startswith(item) and not any(f.startswith(x) for x in PACK_EXCLUDE)]
            if not sub:
                missing.append(item)
            chosen.extend(sub)
        else:
            if item in files:
                chosen.append(item)
            else:
                missing.append(item)
    if missing:
        die("в репозитории нет частей пака: %s" % ", ".join(missing))
    seen, out = set(), []
    for f in chosen:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def build_zip(root, files):
    zpath = os.path.join(root, "dist", PACK_NAME + ".zip")
    safe_reset(root, zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for rp in files:
            zi = zipfile.ZipInfo(PACK_NAME + "/" + rp, date_time=ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            # Имена латиницей (check_kit); для не-ASCII имён zipfile сам ставит флаг UTF-8.
            mode = 0o755 if rp.endswith(".sh") else 0o644
            zi.external_attr = (0o100000 | mode) << 16
            with open(os.path.join(root, *rp.split("/")), "rb") as fh:
                zf.writestr(zi, fh.read())
    return zpath


def git_commit(root):
    """(коммит, грязное ли дерево, текст git status). Не git — (None, None, '')."""
    try:
        dirty = subprocess.check_output(["git", "-C", root, "-c", "core.quotepath=off",
                                         "status", "--porcelain"],
                                        stderr=subprocess.DEVNULL).decode("utf-8", "replace")
    except Exception:
        return None, None, ""
    try:
        out = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"],
                                      stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        out = None  # репозиторий без единого коммита
    return out, bool(dirty.strip()), dirty


def verify(root, site_files, site_dir, pack, zpath):
    """Контрольные суммы: репозиторий = витрина = архив."""
    bad = []
    repo_sum = {}
    for rp in site_files:
        repo_sum[rp] = sha256_file(os.path.join(root, *rp.split("/")))
        s = sha256_file(os.path.join(site_dir, *rp.split("/")))
        if s != repo_sum[rp]:
            bad.append("витрина ≠ репозиторий: " + rp)
    zip_sum = {}
    with zipfile.ZipFile(zpath) as zf:
        names = set(zf.namelist())
        for rp in pack:
            name = PACK_NAME + "/" + rp
            if name not in names:
                bad.append("нет в архиве: " + rp)
                continue
            zip_sum[rp] = hashlib.sha256(zf.read(name)).hexdigest()
            if zip_sum[rp] != repo_sum.get(rp):
                bad.append("архив ≠ репозиторий: " + rp)
        extra = names - {PACK_NAME + "/" + rp for rp in pack}
        for n in sorted(extra):
            bad.append("лишнее в архиве: " + n)
    return repo_sum, zip_sum, bad


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Сборка витрины и выпускного пака kit 2.0")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="собрать из незакоммиченного дерева — только локальная проба, не публиковать")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    commit, dirty, status = git_commit(root)
    if dirty is None:
        die("это не git-репозиторий: сборка для публикации берёт файлы только из git.")
    if (dirty or commit is None) and not args.allow_dirty:
        print(status.rstrip()[:2000])
        die("в рабочем дереве есть незакоммиченные изменения (source_dirty). "
            "Публикуется только закоммиченное: сделайте commit и запустите снова. "
            "Для локальной пробы без публикации: --allow-dirty")
    trial = bool(dirty or commit is None)

    run_check(root)

    files = repo_files(root, allow_dirty=args.allow_dirty)
    print("→ витрина: %d файлов" % len(files))
    site_dir = build_site(root, files)

    pack = pack_files(root, files)
    print("→ выпускной пак: %d файлов" % len(pack))
    zpath = build_zip(root, pack)

    repo_sum, zip_sum, bad = verify(root, files, site_dir, pack, zpath)
    if bad:
        for b in bad:
            print("  ✗ " + b)
        die("контрольные суммы не сошлись — публикация остановлена.")

    manifest = {
        "kit_version": "2.0",
        "built_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "source_commit": commit,
        "source_dirty": dirty,
        "local_trial": trial,
        "site": {"path": "dist/site/", "files": repo_sum},
        "graduation_pack": {
            "path": "dist/" + PACK_NAME + ".zip",
            "root_folder": PACK_NAME + "/",
            "sha256": sha256_file(zpath),
            "files": zip_sum,
        },
    }
    mpath = os.path.join(root, "dist", "manifest.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    stop = os.path.join(root, "dist", "DO_NOT_PUBLISH.txt")
    if trial:
        with open(stop, "w", encoding="utf-8") as fh:
            fh.write("Локальная проба (--allow-dirty): собрано из незакоммиченного дерева.\n"
                     "НЕ публиковать. Для публикации — commit и сборка без --allow-dirty.\n")
    elif os.path.exists(stop):
        safe_reset(root, stop)

    print("✓ готово" + (" — ЛОКАЛЬНАЯ ПРОБА, не публиковать" if trial else ""))
    print("  dist/site/                  — витрина /aipotok/skills/")
    print("  dist/%s.zip — выпускной пак" % PACK_NAME)
    print("  dist/manifest.json          — контрольные суммы")
    if trial:
        print("  ⚠ собрано с --allow-dirty из незакоммиченного дерева: manifest.json помечен "
              "local_trial, рядом лежит DO_NOT_PUBLISH.txt. Не публикуйте эту сборку.")


if __name__ == "__main__":
    main()
