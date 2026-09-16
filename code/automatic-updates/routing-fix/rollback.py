import hashlib,json,os
from pathlib import Path
b=Path('/root/gpd-egpu-display-routing-fix')
assert os.geteuid()==0
rows=json.loads((b/'records.json').read_text())
for r in rows:
    assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest() in (r['before'],r['after']), 'Later change detected: '+r['path']
    assert hashlib.sha256((b/r['backup']).read_bytes()).hexdigest()==r['before']
for r in reversed(rows):
    p=Path(r['path']); t=p.with_name(p.name+'.routing-rollback')
    with t.open('xb') as f:
        f.write((b/r['backup']).read_bytes()); f.flush(); os.fsync(f.fileno())
    t.chmod(r['mode']); os.replace(t,p)
print('Routing files restored. Live drivers untouched. Undo this layer before earlier update-support rollback.')
