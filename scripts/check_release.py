"""Fail closed if private/generated files or common credential formats are tracked."""
from pathlib import Path
import re
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
names=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
patterns=[re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
          re.compile(r'\b(?:ghp_|github_pat_|sk_live_)[A-Za-z0-9_]{20,}'),
          re.compile(r'\bAKIA[0-9A-Z]{16}\b')]
failures=[]
for name in filter(None,names):
    path=Path(name)
    if any(part in {'data','outputs','backups','.runtime','node_modules','dist','__pycache__'} or part.startswith('.venv') for part in path.parts) or path.name.startswith('.env') and path.name!='.env.example' or path.suffix in {'.sqlite3','.db','.log','.pem','.key'}:
        failures.append(name+': private/generated path')
        continue
    raw=(root/name).read_bytes()
    if b'\0' not in raw:
        text=raw.decode('utf-8',errors='replace')
        if any(pattern.search(text) for pattern in patterns):failures.append(name+': credential-shaped text')
        if ('/'+'Users'+'/') in text:failures.append(name+': personal absolute path')
if failures:
    print('\n'.join(failures));sys.exit(1)
print(f'Release scan passed: {len(list(filter(None,names)))} tracked files. This targeted scan is not a comprehensive security audit.')
