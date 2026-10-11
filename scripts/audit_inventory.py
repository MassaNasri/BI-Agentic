"""Read-only source inventory for Phase 0. Never emits environment secret values."""
from pathlib import Path
import ast
import collections
import json
import os
import re
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'audit'
SKIP = {'.git', 'node_modules', '__pycache__', '.pytest_cache', '.venv', 'venv', 'timesfm', 'data', 'logs', 'media', 'dist', 'build'}
SECRET = re.compile(r'password|passwd|secret|token|api.?key|credential|private.?key', re.I)

def redact(s):
    s = re.sub(r'(https?://)[^\s/@:]+:[^\s/@]+@', r'\1[REDACTED]@', s)
    s = re.sub(r'(sk-[A-Za-z0-9_-]{12,})', '[REDACTED]', s)
    if SECRET.search(s):
        s = re.sub(r'([\"\'])([^\"\']*)\1', lambda m: m.group(0) if re.fullmatch(r'[A-Z][A-Z0-9_]+', m.group(2)) or not m.group(2) else '\"[REDACTED]\"', s)
        s = re.sub(r'(:\s*|=\s*)([^\s#]+)(\s*(?:#.*)?)$', r'\1[REDACTED]\3', s)
    return s

def source_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in sorted(files):
            p = Path(base) / name
            if p.suffix in {'.py','.js','.jsx','.json','.yml','.yaml','.toml','.sh','.ps1','.sql','.xml'} or name in {'Dockerfile','.gitignore','.dockerignore','requirements.txt','.env.example'}:
                if name in {'package-lock.json'} or name.startswith('.env') and name != '.env.example':
                    continue
                yield p

def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'read':
        for arg in sys.argv[2:]:
            bits = arg.rsplit(':',2)
            rel = bits[0]
            start = int(bits[1]) if len(bits)>1 else 1
            end = int(bits[2]) if len(bits)>2 else 100000
            p = ROOT / rel
            print('\nFILE',rel)
            for n,line in enumerate(p.read_text(encoding='utf-8-sig', errors='replace').splitlines(),1):
                if start<=n<=end:
                    print(f'{n}: {redact(line)}')
        return
    OUT.mkdir(parents=True,exist_ok=True)
    result = {'scope': 'Source inventory; runtime state is separate. Vendor TimesFM excluded from first-party counts.', 'files': [], 'compose': {}, 'environment': [], 'routes': [], 'models': [], 'dependencies': {}, 'tests': [], 'syntax_errors': []}
    env = collections.defaultdict(list)
    for p in source_files():
        rel = p.relative_to(ROOT).as_posix()
        content = p.read_text(encoding='utf-8-sig',errors='replace')
        lines = content.splitlines()
        result['files'].append({'path':rel,'lines':len(lines)})
        if p.name.startswith('test') or p.name.endswith(('.test.js','.spec.js')):
            result['tests'].append(rel)
        if p.name == 'requirements.txt':
            result['dependencies'][rel] = [redact(l) for l in lines if l.strip() and not l.lstrip().startswith('#')]
        if p.name == 'docker-compose.yml':
            obj = yaml.safe_load(content)
            services = {}
            for name,s in obj.get('services',{}).items():
                entry = {k:s[k] for k in ['image','build','ports','expose','depends_on','volumes','networks','restart','user','deploy','extends'] if k in s}
                entry['healthcheck'] = {k:([redact(str(x)) for x in v] if isinstance(v,list) else v) for k,v in s.get('healthcheck',{}).items()}
                entry['environment_names'] = list(s.get('environment',{}))
                entry['env_file'] = s.get('env_file',[])
                services[name]=entry
            result['compose'][rel] = {'services':services,'volumes':obj.get('volumes',{}),'networks':obj.get('networks',{})}
        if p.suffix == '.py':
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node,ast.Call):
                        fn = ast.unparse(node.func)
                        if fn in {'os.getenv','os.environ.get','env','env.bool','env.int','os.environ.setdefault'} and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                            key = node.args[0].value
                            env[key].append({'file':rel,'line':node.lineno,'has_default':len(node.args)>1 or any(k.arg=='default' for k in node.keywords),'secret':bool(SECRET.search(key))})
                        if fn in {'path','re_path','router.register'} and node.args:
                            result['routes'].append({'file':rel,'line':node.lineno,'declaration':redact(ast.unparse(node))})
                    if isinstance(node,ast.ClassDef) and any('Model' in ast.unparse(b) for b in node.bases):
                        result['models'].append({'file':rel,'line':node.lineno,'class':node.name,'definition':redact(ast.unparse(node))})
            except SyntaxError as e:
                result['syntax_errors'].append({'file':rel,'line':e.lineno,'error':e.msg})
        for n,line in enumerate(lines,1):
            for m in re.finditer(r'\$\{([A-Z][A-Z0-9_]*)([^}]*)\}|import\.meta\.env\.([A-Z][A-Z0-9_]*)',line):
                key = m.group(1) or m.group(3)
                env[key].append({'file':rel,'line':n,'required':bool(m.group(2) and ':?' in m.group(2)),'secret':bool(SECRET.search(key))})
    result['environment'] = [{'name':k,'references':v} for k,v in sorted(env.items())]
    result['local_env_names'] = {}
    for p in ROOT.rglob('.env*'):
        if any(x in SKIP for x in p.relative_to(ROOT).parts): continue
        result['local_env_names'][p.relative_to(ROOT).as_posix()] = [m.group(1) for l in p.read_text(encoding='utf-8-sig',errors='replace').splitlines() if (m:=re.match(r'^([A-Z][A-Z0-9_]*)=',l))]
    for args,key in [(['status','--short'],'git_status_before'),(['branch','--show-current'],'git_branch'),(['log','-1','--format=%h %cs %s'],'git_head')]:
        proc = subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True)
        result[key]=proc.stdout.strip() if proc.returncode==0 else 'NOT VERIFIED'
    (OUT/'inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(result['files']),'routes':len(result['routes']),'models':len(result['models']),'env_names':len(env),'test_files':len(result['tests']),'syntax_errors':result['syntax_errors'],'compose_services':{p:list(v['services']) for p,v in result['compose'].items()}},indent=2))

if __name__ == '__main__':
    main()
