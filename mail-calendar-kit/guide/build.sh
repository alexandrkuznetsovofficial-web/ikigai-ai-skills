#!/bin/bash
# Пересборка методички «Почта и календарь во втором мозге»: guide.html → PDF (Chrome headless).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-Vtoroy_mozg_pochta_kalendar_$(date +%Y-%m-%d)}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PDF="$HOME/Downloads/$OUT.pdf"

"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --virtual-time-budget=12000 --print-to-pdf="$PDF" "file://$DIR/guide.html" 2>/dev/null

python3 - "$PDF" <<'PYEOF'
import re, sys
d = open(sys.argv[1], 'rb').read()
print(f"готово: {sys.argv[1]}")
print("страниц:", len(re.findall(rb'/Type\s*/Page[^s]', d)),
      "· ссылок:", len(re.findall(rb'/URI', d)),
      "· размер:", round(len(d)/1024), "КБ")
PYEOF
