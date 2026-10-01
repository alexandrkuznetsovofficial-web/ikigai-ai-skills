#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Граф знаний памяти → один HTML-файл (открывается в браузере, без интернета).

Узлы — заметки памяти (без sessions/ и секретных папок). Рёбра — [[ссылки]] и markdown-ссылки
на .md. Ссылка находится по имени файла, по полю `name:` из шапки и с заменой «-» ↔ «_»,
поэтому оба вида — [[имя_файла]] и [[name-slug]] — рабочие. Цвет — стадия сада (stage:),
размер — число связей.

Куда кладётся (ВНЕ папки памяти, чтобы имена личных файлов не уехали в облако или на сервер):
  Mac / Linux:  ~/.claude/graph/memory_graph.html  + memory_graph_stats.json + force-graph.min.js
  Windows:      %USERPROFILE%\\.claude\\graph\\...
Библиотека force-graph (MIT, v1.43.5) копируется рядом из папки vendor/ — без CDN.

Запуск (Python 3.8+, без зависимостей):
  python3 build_memory_graph.py                 построить граф
  python3 build_memory_graph.py --no-personal   без personal/ и private/ на любом уровне (для показа
                                                на экране); заметки и папки secret* не попадают никогда
  python3 build_memory_graph.py --stats         только посчитать и вывести JSON, ничего не писать
  python3 build_memory_graph.py --root ПУТЬ     папка памяти явно (по умолчанию <workspace>/memory)
  python3 build_memory_graph.py --out ПАПКА     куда положить граф (по умолчанию ~/.claude/graph)
"""
import argparse
import collections
import datetime
import html
import json
import os
import posixpath
import re
import shutil
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".obsidian", ".secrets", "node_modules", ".trash"}
WIKI = re.compile(r"\[\[([^\]]+)\]\]")
MDLINK = re.compile(r"\]\(([^)\s]+?\.md)(?:#[^)]*)?\)")
LIB = "force-graph.min.js"


def find_root(arg_root):
    if arg_root:
        return Path(arg_root).expanduser().resolve()
    env = Path.home() / ".claude" / "ikigai_env.json"
    try:
        ws = json.loads(env.read_text(encoding="utf-8")).get("workspace")
        if ws:
            p = Path(ws).expanduser() / "memory"
            if p.is_dir():
                return p.resolve()
    except Exception:
        pass
    cwd = Path.cwd()
    if (cwd / "memory").is_dir():
        return (cwd / "memory").resolve()
    if cwd.name == "memory":
        return cwd.resolve()
    return None


def skip_dir(name):
    low = name.lower()
    return name in SKIP_DIRS or low.startswith("secret") or low.startswith(".secret")


def key(s):
    s = s.strip().lower()
    if s.endswith(".md"):
        s = s[:-3]
    return s.replace("-", "_")


KEY_LINE = re.compile(r"^\s*[A-Za-z_][\w\-]*:(\s|$)")


def frontmatter(text):
    """Только шапка заметки (между первой и второй строкой '---'), не тело.
    «---» в начале может быть просто горизонтальной линией: шапка считается шапкой, только если
    между двумя '---' есть хотя бы одна строка вида «ключ:»."""
    if not text.startswith("---"):
        return ""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            head = lines[1:i]
            return "\n".join(head) if any(KEY_LINE.match(l) for l in head) else ""
    return ""


def field(head, name):
    m = re.search(r"^\s*" + re.escape(name) + r":\s*(.+?)\s*$", head, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def is_secretish(s):
    return "secret" in s.lower()


PRIVATE_DIRS = {"personal", "private"}


def is_private_path(rel_posix):
    """--no-personal: путь лежит в personal/ или private/ на любом уровне вложенности."""
    return any(p.lower() in PRIVATE_DIRS for p in rel_posix.split("/")[:-1])


def _utf8_stdout():
    """Windows / Git Bash: вывод в канал идёт в cp1251/cp1252 и падает на кириллице — переключаем на UTF-8."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="Граф памяти → HTML")
    ap.add_argument("--root", help="папка памяти (по умолчанию <workspace>/memory)")
    ap.add_argument("--out", help="папка для графа (по умолчанию ~/.claude/graph)")
    ap.add_argument("--no-personal", action="store_true", help="не включать папку personal/")
    ap.add_argument("--stats", action="store_true", help="только статистика в stdout, файлы не писать")
    a = ap.parse_args()

    root = find_root(a.root)
    if root is None or not root.is_dir():
        print("Не нашёл папку памяти. Укажи её: --root <рабочая папка>/memory", file=sys.stderr)
        return 2
    out_dir = Path(a.out).expanduser() if a.out else Path.home() / ".claude" / "graph"
    skip_top = {"sessions"}

    notes = {}
    by_stem = collections.defaultdict(list)
    by_name = {}
    hidden = set()
    for dp, dn, fn in os.walk(str(root)):
        rel_dir = Path(dp).relative_to(root)
        if rel_dir.parts and rel_dir.parts[0] in skip_top:
            dn[:] = []
            continue
        dn[:] = sorted(d for d in dn if not skip_dir(d))
        for f in sorted(fn):
            if not f.endswith(".md") or f.lower().startswith("secret"):
                continue
            full = Path(dp) / f
            rel = full.relative_to(root).as_posix()
            try:
                text = full.read_text(encoding="utf-8", errors="ignore").lstrip("﻿")
            except Exception:
                continue
            text = text.replace("\r\n", "\n")
            head = frontmatter(text)
            if a.no_personal and is_private_path(rel.lower()):
                # личную заметку в граф не берём, но запоминаем её имена: ссылки на неё
                # не должны всплыть в статистике «битых» даже именем файла
                hidden.add(key(f))
                if field(head, "name"):
                    hidden.add(key(field(head, "name")))
                continue
            notes[rel] = {"text": text, "name": field(head, "name"),
                          "stage": field(head, "stage") or "none", "para": field(head, "para") or "none"}
            by_stem[key(f)].append(rel)
            if notes[rel]["name"]:
                by_name.setdefault(key(notes[rel]["name"]), rel)

    def resolve(target, src):
        t = target.split("|")[0].split("#")[0].strip()
        if not t or t.startswith(("http:", "https:", "/", "mailto:")):
            return None
        t = t.replace("\\", "/")
        if t.endswith(".md") or "/" in t:
            cand = posixpath.normpath(posixpath.join(posixpath.dirname(src), t))
            if cand in notes:
                return cand
            cand = posixpath.normpath(t)
            if cand in notes:
                return cand
        k = key(t.split("/")[-1])
        if k in by_stem:
            return by_stem[k][0]
        return by_name.get(k)

    edges = set()
    broken = collections.Counter()
    for rel, n in notes.items():
        for raw in WIKI.findall(n["text"]) + MDLINK.findall(n["text"]):
            dst = resolve(raw, rel)
            if dst and dst != rel:
                edges.add(tuple(sorted((rel, dst))))
            elif dst is None:
                tgt = raw.split("|")[0].strip()
                if (not tgt or tgt.startswith(("http", "/")) or "(" in tgt or is_secretish(tgt)
                        or (a.no_personal and (is_private_path(tgt.lower())
                                               or key(tgt.split("/")[-1]) in hidden))):
                    continue          # секретное и личное в статистику не попадает даже именем
                broken[tgt] += 1

    deg = collections.Counter()
    for x, y in edges:
        deg[x] += 1
        deg[y] += 1

    order = sorted(notes)
    ids = {rel: i for i, rel in enumerate(order)}
    nodes = [{"id": ids[r], "p": r, "t": (notes[r]["name"] or posixpath.basename(r)[:-3])[:90],
              "s": notes[r]["stage"], "a": notes[r]["para"], "d": deg[r]} for r in order]
    links = [{"source": ids[x], "target": ids[y]} for x, y in sorted(edges)]
    linked = sum(1 for r in notes if deg[r] > 0)
    staged = sum(1 for n in notes.values() if n["stage"] in ("seed", "sprout", "evergreen"))
    stats = {
        "built": datetime.datetime.now().isoformat(timespec="minutes"),
        "notes": len(notes), "edges": len(edges),
        "linked_notes": linked, "linked_share": round(linked / max(len(notes), 1), 3),
        "stage_share": round(staged / max(len(notes), 1), 3),
        "broken_links": sum(broken.values()), "top_broken": broken.most_common(15),
        "stage": dict(collections.Counter(n["stage"] for n in notes.values())),
        "no_personal": a.no_personal,
    }

    summary = "%d заметок · %d связей · связано %d%% · %s" % (
        len(notes), len(edges), round(stats["linked_share"] * 100), stats["built"])

    if a.stats:
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    lib_src = Path(__file__).resolve().parent / "vendor" / LIB
    lib_dst = out_dir / LIB
    if lib_src.is_file():
        if not lib_dst.is_file() or lib_dst.read_bytes() != lib_src.read_bytes():
            shutil.copyfile(str(lib_src), str(lib_dst))
    elif not lib_dst.is_file():
        print("ВНИМАНИЕ: нет vendor/%s рядом со скриптом — граф не нарисуется. "
              "Переустанови скилл memory-garden целиком." % LIB, file=sys.stderr)

    (out_dir / "memory_graph_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    data = json.dumps({"nodes": nodes, "links": links}, ensure_ascii=False)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = PAGE.replace("__DATA__", data).replace("__STATS__", html.escape(summary))
    (out_dir / "memory_graph.html").write_text(page, encoding="utf-8")
    print(summary)
    print("битых ссылок: %d · файл: %s" % (stats["broken_links"], out_dir / "memory_graph.html"))
    return 0


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Граф памяти</title>
<style>:root{--bg:#0f1115;--fg:#e6e6e6;--mut:#8a8f98}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#fafaf7;--fg:#1d1d1f;--mut:#6b6b70}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;overflow:hidden}
#hud{position:fixed;top:12px;left:16px;right:16px;z-index:2;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
#hud input{background:transparent;color:var(--fg);border:1px solid var(--mut);border-radius:8px;padding:6px 10px;min-width:200px}
.lg{color:var(--mut)} .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 4px 0 10px}
#info{position:fixed;bottom:12px;left:16px;right:16px;color:var(--mut);z-index:2}</style></head><body>
<div id="hud"><b>Граф памяти</b><input id="q" placeholder="Найти заметку…">
<span class="lg"><span class="dot" style="background:#7bc96f"></span>росток<span class="dot" style="background:#3fa7d6"></span>побег<span class="dot" style="background:#e0a526"></span>вечнозелёная<span class="dot" style="background:#777"></span>без стадии</span>
<span class="lg">__STATS__</span></div><div id="g"></div><div id="info">Наведите на точку — путь заметки. Клик — приблизить.</div>
<script src="force-graph.min.js"></script>
<script>
if(typeof ForceGraph==="undefined"){document.getElementById("info").textContent="Не загрузилась библиотека force-graph.min.js — она должна лежать в той же папке, что и этот файл. Пересобери граф скриптом build_memory_graph.py.";}
else{
const E=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const D=__DATA__;const C={seed:"#7bc96f",sprout:"#3fa7d6",evergreen:"#e0a526"};
const G=ForceGraph()(document.getElementById("g")).graphData(D).nodeId("id")
.nodeVal(n=>1+Math.sqrt(n.d)).nodeColor(n=>n.hl?"#ff4d6d":(C[n.s]||"#777"))
.nodeLabel(n=>E(n.t)+"<br><small>"+E(n.p)+" · "+E(n.a)+" · связей "+n.d+"</small>")
.linkColor(()=>"rgba(140,140,150,.25)").cooldownTicks(200)
.onNodeHover(n=>{document.getElementById("info").textContent=n?n.p:"Наведите на точку — путь заметки. Клик — приблизить."})
.onNodeClick(n=>{G.centerAt(n.x,n.y,600);G.zoom(4,600)});
document.getElementById("q").oninput=e=>{const v=e.target.value.toLowerCase();D.nodes.forEach(n=>n.hl=v&&(n.t.toLowerCase().includes(v)||n.p.toLowerCase().includes(v)));G.nodeColor(G.nodeColor());};
addEventListener("resize",()=>G.width(innerWidth).height(innerHeight));
}
</script></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
