import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
tpl = ROOT / 'templates' / 'admin.html'
data = tpl.read_text(encoding='utf8')
scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', data, flags=re.IGNORECASE)
code = '\n'.join(scripts)
for i, line in enumerate(code.splitlines(), start=1):
    if 'catch' in line or 'try' in line or 'async' in line:
        print(f"{i:04d}: {line}")
print('\n--- Full script written to tmp_admin_js_for_debug.js')
open(ROOT / 'tmp_admin_js_for_debug.js','w',encoding='utf8').write(code)
