#!/usr/bin/env python3
import concurrent.futures
import json, os, subprocess, sys, threading
from pathlib import Path

REPO_ROOT = Path('/home/ubuntu/repos')
OUT_DIR = Path(__file__).parent / 'dogfood_continue_695'
SAMPLE_FILE = Path(__file__).parent / 'dogfood_continue_695_sample.json'
TIMEOUT = 600
PRINT_LOCK = threading.Lock()

def load_sample():
    data = json.loads(SAMPLE_FILE.read_text())
    return [(d['repo'], d['lang'], Path(d['file'])) for d in data]

def audit_one(args):
    repo, language, path = args
    rel = path.relative_to(REPO_ROOT / repo)
    safe_name = str(rel).replace('/','__')
    out_path = OUT_DIR / f"{repo}__{safe_name}.json"
    if out_path.exists():
        data = json.loads(out_path.read_text())
        status = data.get('verification_status','unknown')
        errors = data.get('errors',[])
        with PRINT_LOCK:
            print(f'[cached] {path} -> {status} (errors={len(errors)})', flush=True)
        return dict(repo=repo, file=str(rel), lang=language, status=status, errors=errors)
    try:
        result = subprocess.run(['uv','run','python','-m','agent','audit','--code-file',str(path),'--language',language,'--format','json'], cwd='/home/ubuntu/repos/mumei-agent', env={**os.environ,'LLM_API_KEY':''}, capture_output=True, text=True, timeout=TIMEOUT)
        text = result.stdout or result.stderr
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = dict(raw_output=text, returncode=result.returncode)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        status = data.get('verification_status','unknown')
        errors = data.get('errors',[])
        with PRINT_LOCK:
            print(f'[no-llm] {path} -> {status} (errors={len(errors)})', flush=True)
        return dict(repo=repo, file=str(rel), lang=language, status=status, errors=errors)
    except subprocess.TimeoutExpired:
        data = dict(verification_status='timeout')
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        with PRINT_LOCK:
            print(f'[timeout] {path}', flush=True)
        return dict(repo=repo, file=str(rel), lang=language, status='timeout', errors=['timeout'])

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sample = load_sample()
    summary = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        for result in executor.map(audit_one, sample):
            summary.append(result)
    (OUT_DIR / '_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nSummary written to', OUT_DIR / '_summary.json')
    return 0

if __name__ == '__main__':
    sys.exit(main())
