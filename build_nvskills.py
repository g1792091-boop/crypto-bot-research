# NVIDIA/skills 저장소 → 누리용 묶음 (index.json + 스킬별 .json.gz)
import os, json, gzip, re, sys, shutil, subprocess
src = sys.argv[1]; out = sys.argv[2]
shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
TEXT = {'.md','.py','.sh','.yaml','.yml','.toml','.txt','.json','.cfg','.config','.ini','.ps1','.c','.cu','.h','.cpp','.tf','.csv','.example','.html','.js','.ts','.j2','.jinja','.env','.mps','.gitignore','.dockerfile'}
groups = {}
try:
    for g in json.load(open(os.path.join(src, 'skills.sh.json'))).get('groupings', []):
        for n in g.get('skills', []): groups.setdefault(n, g['title'])
except Exception as e: print('groups', e)
commit = subprocess.run(['git','-C',src,'log','-1','--format=%h %cs'],capture_output=True,text=True).stdout.strip()
def front(t):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', t, re.S)
    if not m: return {}, t
    head, body = m.group(1), m.group(2)
    lines = head.split('\n'); d = {}
    for i, l in enumerate(lines):
        mm = re.match(r'^([\w-]+):\s*(.*)$', l)
        if not mm: continue
        k, v = mm.group(1), mm.group(2).strip()
        if re.match(r'^[>|]-?$', v):
            v = ' '.join(x.strip() for x in lines[i+1:] if re.match(r'^\s+\S', x) and True)
            # 다음 키 전까지만
            buf = []
            for x in lines[i+1:]:
                if re.match(r'^\s+\S', x): buf.append(x.strip())
                else: break
            v = ' '.join(buf)
        d[k] = v.strip('"\'')
    tags = re.findall(r'^\s+-\s+([\w.+-]+)\s*$', head, re.M)
    d['_tags'] = tags
    return d, body
index = []; total = 0; skipped = 0
for name in sorted(os.listdir(os.path.join(src, 'skills'))):
    root = os.path.join(src, 'skills', name)
    sk = os.path.join(root, 'SKILL.md')
    if not os.path.isfile(sk): continue
    files = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if not x.startswith('.git') and x != '__pycache__']
        for f in fn:
            p = os.path.join(dp, f); rel = os.path.relpath(p, root)
            ext = os.path.splitext(f)[1].lower() or ('.'+f.lower() if f.startswith('.') else '')
            if ext not in TEXT and f not in ('Dockerfile','Makefile','LICENSE','Skill'):
                skipped += 1; continue
            if os.path.getsize(p) > 3_000_000: skipped += 1; continue
            try: files[rel] = open(p, encoding='utf-8').read()
            except Exception: skipped += 1
    fm, body = front(files['SKILL.md'])
    data = json.dumps({'name': name, 'files': files}, ensure_ascii=False).encode()
    gz = gzip.compress(data, 9)
    open(os.path.join(out, name + '.json.gz'), 'wb').write(gz)
    total += len(gz)
    meta = fm.get('metadata', '')
    index.append({'n': name, 'd': re.sub(r'\s+', ' ', fm.get('description', ''))[:400], 'w': re.sub(r'\s+', ' ', fm.get('when_to_use', ''))[:200],
                  'g': groups.get(name, '기타'), 't': fm['_tags'][:10], 'f': len(files), 'z': len(gz)})
for lic in ('LICENSE-APACHE','LICENSE-CC-BY-4.0'):
    shutil.copy(os.path.join(src, lic), out)
json.dump({'source': 'https://github.com/NVIDIA/skills', 'commit': commit, 'count': len(index), 'skills': index}, open(os.path.join(out, 'index.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
print('skills', len(index), 'gz MB', round(total/1e6, 1), 'skipped files', skipped, 'index KB', os.path.getsize(os.path.join(out,'index.json'))//1024)
