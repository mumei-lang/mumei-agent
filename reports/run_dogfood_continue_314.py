#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

REPO_ROOT = Path('/home/ubuntu/repos')
OUT_DIR = Path(__file__).parent / 'dogfood_continue_314'
SAMPLE_FILE = Path(__file__).parent / 'dogfood_continue_314_sample.json'
TIMEOUT = 240

def load_sample():
    data = json.loads(SAMPLE_FILE.read_text())
    return [(d['repo'], d['lang'], Path(d['file'])) for d in data]

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary=[]
    for repo, language, path in load_sample():
        rel = path.relative_to(REPO_ROOT / repo)
        safe_name = str(rel).replace('/','__')
        out_path = OUT_DIR / f"{repo}__{safe_name}.json"
        if out_path.exists():
            data=json.loads(out_path.read_text())
            status=data.get('verification_status','unknown')
            errors=data.get('errors',[])
            print(f'[cached] {path} -> {status} (errors={len(errors)})', flush=True)
            summary.append({'repo':repo,'file':str(rel),'lang':language,'status':status,'errors':errors})
            continue
        print(f'[no-llm] {path}', flush=True)
        try:
            result=subprocess.run(['uv','run','python','-m','agent','audit','--code-file',str(path),'--language',language,'--format','json'], cwd='/home/ubuntu/repos/mumei-agent', env={**os.environ,'LLM_API_KEY':''}, capture_output=True, text=True, timeout=TIMEOUT)
            text=result.stdout or result.stderr
            try:
                data=json.loads(text)
            except json.JSONDecodeError:
                data={'raw_output':text,'returncode':result.returncode}
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            status=data.get('verification_status','unknown')
            errors=data.get('errors',[])
            print(f'  -> {status} (errors={len(errors)})', flush=True)
            summary.append({'repo':repo,'file':str(rel),'lang':language,'status':status,'errors':errors})
        except subprocess.TimeoutExpired:
            data={'verification_status':'timeout'}
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'  -> timeout', flush=True)
            summary.append({'repo':repo,'file':str(rel),'lang':language,'status':'timeout','errors':['timeout']})
    (OUT_DIR / '_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nSummary written to {OUT_DIR / "_summary.json"}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
