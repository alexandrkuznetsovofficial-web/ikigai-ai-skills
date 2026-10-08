#!/usr/bin/env python3
"""Скачивает актуальный кит Икигай и ставит скиллы связки: ikigai-preflight, brain-link и second-brain-audit.

Источник 1 — GitHub (main), источник 2 — витрина ikigai-community.com (если GitHub недоступен).
Старые версии скиллов не удаляются: переезжают в ~/.claude/skills_old/<имя>-<время>.
Секретов не читает, на сервер не ходит. Печатает один JSON, поле human — что сказать человеку.

Mac:     python3 kit_fetch.py
Windows: py -3 kit_fetch.py
"""
import io, json, os, re, shutil, sys, time, urllib.request, zipfile
from pathlib import Path

REPO = "alexandrkuznetsovofficial-web/ikigai-ai-skills"
SITE = "https://ikigai-community.com/aipotok/skills/start"  # запасной источник: папка start/ витрины
SKILLS = ("ikigai-preflight", "brain-link", "second-brain-audit")
# файлы-гайды, которые гайд связки открывает по ходу (лежат в распаковке, в skills не ставятся)
GUIDES = ("KIT_CONVENTIONS.md", "SETUP_MORNING_BRIEF.md", "meeting-2-3/auto-commit-backup.md",
          "novoselie-server-kit/audit/server_access.example")
HOME = Path(os.environ.get("KIT_HOME") or Path.home())
SK = HOME / ".claude" / "skills"
VER = re.compile(r"kit_version:\s*([0-9]+(?:\.[0-9]+)*)")
OLD = HOME / ".claude" / "skills_old"  # вне skills: Claude Code и синк их не подхватят

for _s in (sys.stdout, sys.stderr):  # Windows: Claude Code читает вывод через пайп — только UTF-8
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "ikigai-kit-fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    head = data[:200].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html")):  # витрина отдаёт HTML-страницу с кодом 200 на любой несуществующий путь
        raise IOError("вместо файла пришла HTML-страница: " + url)
    if url.endswith(".zip") and not data.startswith(b"PK"):
        raise IOError("это не zip: " + url)
    return data


def ver(path):
    try:
        m = VER.search(path.read_text(encoding="utf-8", errors="ignore")[:3000])
        return m.group(1) if m else None
    except OSError:
        return None


def vt(v):
    try:
        return tuple(int(x) for x in v.split(".")) if v else ()
    except ValueError:
        return ()


def skip(rel):
    parts = rel.split("/")
    return (not rel or parts[0] in ("dist", "tools", ".github")
            or bool({"ci", "tests", "__pycache__"} & set(parts[:-1])))


def unpack(z, dst, strip_root):
    root = z.namelist()[0].split("/")[0] if strip_root else ""
    base = dst.resolve()
    for n in z.namelist():
        rel = (n[len(root) + 1:] if root else n).replace("\\", "/")
        name = rel.rstrip("/").split("/")[-1]
        if skip(rel) or rel.startswith("__MACOSX/") or name.startswith("._") or name == ".DS_Store":
            continue
        out = dst / rel
        if base != out.resolve() and base not in out.resolve().parents:  # путь вне папки распаковки — не пишем
            continue
        if n.endswith("/"):
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))


def from_github(dst):
    try:
        sha = json.loads(get(f"https://api.github.com/repos/{REPO}/commits/main", 20))["sha"][:7]
    except Exception:
        sha = "?"
    z = zipfile.ZipFile(io.BytesIO(get(f"https://github.com/{REPO}/archive/refs/heads/main.zip")))
    unpack(z, dst, strip_root=True)
    return "GitHub", sha


def from_site(dst):
    for name in SKILLS:
        unpack(zipfile.ZipFile(io.BytesIO(get(f"{SITE}/{name}.zip"))), dst, strip_root=False)
    for g in GUIDES:
        out = dst / g
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(get(f"{SITE}/{g.split('/')[-1]}"))
    return "витрина Икигай", "kit " + (ver(dst / "brain-link" / "SKILL.md") or "?")


def main():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = HOME / "Downloads"
    errors = []
    for fetch in (from_github, from_site):
        dst = base / f"ikigai-kit-{stamp}-{fetch.__name__[5:]}"
        dst.mkdir(parents=True, exist_ok=True)
        try:
            source, sha = fetch(dst)
            if all((dst / n / "SKILL.md").exists() for n in SKILLS):
                break
            errors.append(f"{fetch.__name__}: в архиве нет нужных скиллов")
        except Exception as e:
            errors.append(f"{fetch.__name__}: {e.__class__.__name__}")
    else:
        print(json.dumps({"ok": False, "code": 1, "errors": errors,
                          "human": "Не получилось скачать кит ни с GitHub, ни с витрины. Проверь интернет "
                                   "(VPN включён — попробуй выключить, выключен — включить) и запусти ещё раз. "
                                   "Не помогло — скачай «Пробник», «Связку» и «Аудит второго мозга» в кабинете: "
                                   "https://ikigai-community.com/cabinet/academy/skills"},
                         ensure_ascii=False, indent=1))
        sys.exit(1)

    SK.mkdir(parents=True, exist_ok=True)
    installed, moved = [], []
    try:
        for name in SKILLS:
            cur, new = SK / name, SK / f".{name}.new-{stamp}"
            shutil.copytree(dst / name, new)  # сначала новая копия рядом, потом подмена
            if name == "brain-link" and (dst / "KIT_CONVENTIONS.md").exists():
                shutil.copy2(dst / "KIT_CONVENTIONS.md", new / "KIT_CONVENTIONS.md")
            if cur.exists():
                old = OLD / f"{name}-{stamp}"
                OLD.mkdir(parents=True, exist_ok=True)
                os.rename(cur, old)
                moved.append(str(old))
            os.rename(new, cur)
            installed.append({"skill": name, "kit_version": ver(cur / "SKILL.md")})
    except Exception as e:
        print(json.dumps({"ok": False, "code": 1, "error": f"{e.__class__.__name__}: {e}", "installed": installed,
                          "old_versions_moved_to": moved,
                          "human": "Установка скиллов прервалась. Ничего не удалено: старые версии лежат в "
                                   f"{OLD}, новые копии — в {SK} с именем .<скилл>.new-… Закрой программы, которые "
                                   "могут держать папку skills (синк, второе окно VS Code), и запусти скрипт ещё раз."},
                         ensure_ascii=False, indent=1))
        sys.exit(1)

    latest = {}
    for p in dst.rglob("SKILL.md"):
        v = ver(p)
        if v and vt(v) > vt(latest.get(p.parent.name)):
            latest[p.parent.name] = v
    older = []
    for p in sorted(SK.glob("*/SKILL.md")):
        name, have = p.parent.name, ver(p)
        if name in latest and vt(have) < vt(latest[name]):
            older.append(f"{name}: у тебя {have or 'без версии'}, актуальная {latest[name]}")

    print(json.dumps({
        "ok": True, "code": 0, "source": source, "kit_commit": sha, "unpacked_to": str(dst),
        "installed": installed, "old_versions_moved_to": moved, "older_skills": older,
        "guides": {g: str(dst / g) for g in GUIDES if (dst / g).exists()},
        "human": f"Кит скачан ({source}, версия {sha}). Поставлены «Пробник», «Связка» и «Аудит второго мозга»"
                 + (", старые версии сохранены в skills_old" if moved else "") + "."
                 + (f" Устарели ещё {len(older)} скилла(ов) — список в older_skills." if older else ""),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
