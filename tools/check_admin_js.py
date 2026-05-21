import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tpl = ROOT / 'templates' / 'admin.html'
if not tpl.exists():
    print('admin.html not found')
    sys.exit(2)

data = tpl.read_text(encoding='utf8')
scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', data, flags=re.IGNORECASE)
if not scripts:
    print('No <script> blocks found in admin.html')
    sys.exit(0)

code = '\n'.join(scripts)
tmp = ROOT / 'tmp_admin_js.js'
tmp.write_text(code, encoding='utf8')

check_js = (
    "const fs=require('fs');\n"
    "const code=fs.readFileSync('tmp_admin_js.js','utf8');\n"
    "try{ new Function(code); console.log('OK'); }catch(e){ console.error(e && e.stack || e); process.exit(1);}"
)
proc = subprocess.run(['node','-e',check_js], cwd=str(ROOT), capture_output=True, text=True)
print('NODE STDOUT:\n', proc.stdout)
print('NODE STDERR:\n', proc.stderr)
tmp.unlink()
sys.exit(proc.returncode)
