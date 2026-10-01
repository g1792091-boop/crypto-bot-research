# NVIDIA/skills 저장소 → GH Nano 내장 묶음
#   skills/nvidia/index.json      : 스킬 목록(이름·설명·분류)
#   skills/nvidia/<스킬>.json.gz  : 그 스킬 폴더의 모든 파일 (글자 파일은 files, 이미지·서명 등은 bin에 base64)
#   skills/nvidia/_repo.json.gz   : 스킬 폴더 밖의 저장소 파일 전부 (plugins, components.d, docs, .github 등)
# 사용법: python3 build_nvskills.py <NVIDIA/skills 클론 경로> nuri-ai/skills/nvidia
# git이 관리하는 파일(git ls-files)을 하나도 빠짐없이 담고, 끝에 원본과 바이트 단위로 대조한다.
import os, json, gzip, re, sys, shutil, subprocess, base64, hashlib

src, out = sys.argv[1], sys.argv[2]
shutil.rmtree(out, ignore_errors=True); os.makedirs(out)
git = lambda *a: subprocess.run(['git', '-C', src, *a], capture_output=True, text=True, check=True).stdout
tracked = [p for p in git('ls-files', '-z').split('\0') if p]
commit = git('log', '-1', '--format=%h %cs').strip()

groups = {}
for g in json.load(open(os.path.join(src, 'skills.sh.json'))).get('groupings', []):
    for n in g.get('skills', []): groups.setdefault(n, g['title'])

def front(t):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?', t, re.S)
    if not m: return {}
    lines = m.group(1).split('\n'); d = {}
    for i, l in enumerate(lines):
        mm = re.match(r'^([\w-]+):\s*(.*)$', l)
        if not mm: continue
        k, v = mm.group(1), mm.group(2).strip()
        if re.match(r'^[>|]-?$', v):
            buf = []
            for x in lines[i + 1:]:
                if re.match(r'^\s+\S', x): buf.append(x.strip())
                else: break
            v = ' '.join(buf)
        d[k] = v.strip('"\'')
    d['_tags'] = re.findall(r'^\s+-\s+([\w.+-]+)\s*$', m.group(1), re.M)
    return d

def pack(paths, strip):
    files, binf = {}, {}
    for p in paths:
        raw = open(os.path.join(src, p), 'rb').read()
        rel = p[len(strip):] if strip else p
        try:
            txt = raw.decode('utf-8')
            if txt.encode('utf-8') != raw or '\0' in txt: raise ValueError
            files[rel] = txt
        except Exception:
            binf[rel] = base64.b64encode(raw).decode()
    return files, binf

by_skill, repo_files = {}, []
for p in tracked:
    m = re.match(r'^skills/([^/]+)/', p)
    if m and os.path.isfile(os.path.join(src, 'skills', m.group(1), 'SKILL.md')): by_skill.setdefault(m.group(1), []).append(p)
    else: repo_files.append(p)

index, total = [], 0
for name in sorted(by_skill):
    files, binf = pack(by_skill[name], f'skills/{name}/')
    gz = gzip.compress(json.dumps({'name': name, 'files': files, 'bin': binf}, ensure_ascii=False).encode(), 9)
    open(os.path.join(out, name + '.json.gz'), 'wb').write(gz); total += len(gz)
    fm = front(files.get('SKILL.md', ''))
    index.append({'n': name, 'd': re.sub(r'\s+', ' ', fm.get('description', ''))[:400], 'w': re.sub(r'\s+', ' ', fm.get('when_to_use', ''))[:200],
                  'g': groups.get(name, '기타'), 't': fm.get('_tags', [])[:10], 'f': len(files) + len(binf), 'z': len(gz)})
files, binf = pack(repo_files, '')
gz = gzip.compress(json.dumps({'name': '_repo', 'files': files, 'bin': binf}, ensure_ascii=False).encode(), 9)
open(os.path.join(out, '_repo.json.gz'), 'wb').write(gz); total += len(gz)
for lic in ('LICENSE-APACHE', 'LICENSE-CC-BY-4.0'): shutil.copy(os.path.join(src, lic), out)
json.dump({'source': 'https://github.com/NVIDIA/skills', 'commit': commit, 'count': len(index), 'files': len(tracked), 'repoFiles': len(repo_files), 'skills': index},
          open(os.path.join(out, 'index.json'), 'w'), ensure_ascii=False, separators=(',', ':'))

# 대조: 묶음을 다시 풀어 원본 파일과 바이트 단위로 비교
seen = {}
for f in os.listdir(out):
    if not f.endswith('.json.gz'): continue
    d = json.loads(gzip.decompress(open(os.path.join(out, f), 'rb').read()))
    pre = '' if d['name'] == '_repo' else f"skills/{d['name']}/"
    for k, v in d['files'].items(): seen[pre + k] = v.encode('utf-8')
    for k, v in d['bin'].items(): seen[pre + k] = base64.b64decode(v)
missing = [p for p in tracked if p not in seen]
diff = [p for p in tracked if p in seen and hashlib.sha256(seen[p]).digest() != hashlib.sha256(open(os.path.join(src, p), 'rb').read()).digest()]
print(f'NVIDIA/skills {commit}: 스킬 {len(index)}개, 저장소 파일 {len(tracked)}개 중 {len(seen)}개 포함, 빠짐 {len(missing)}, 내용 다름 {len(diff)}, 압축 {total/1e6:.1f}MB')
if missing or diff:
    print('빠짐:', missing[:20], '다름:', diff[:20]); sys.exit(1)
