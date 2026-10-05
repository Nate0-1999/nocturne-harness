import json
import subprocess
import sys
from pathlib import Path

root = Path('/private/tmp/m4sy-01a10a5b')
n = int(sys.argv[1])
record = root / f'walk/scout/small-{n}'
marks = json.loads((record / 'marks.json').read_text())
assert marks['final_state'] == 'completed'
sid = marks['symphony_id']
project = root / f'walk/small-{n}'
branch = f'symphony/{sid}'
target = root / f'walk/restored-result-small-{n}'
target.mkdir()
archive = subprocess.run(['git', '-C', str(project), 'archive', branch], capture_output=True, check=True)
subprocess.run(['tar', '-xf', '-', '-C', str(target)], input=archive.stdout, check=True)
test = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', f'wc{n}', '-p', 'test_counter.py'], cwd=target, capture_output=True, text=True)
paths = subprocess.check_output(['git', '-C', str(project), 'diff', '--name-only', 'main', branch], text=True).splitlines()
run = root / 'live-home/palaces/test-m4sy/symphonies' / sid
models = sorted({m['model_name'] for p in run.rglob('messages.json') for m in json.loads(p.read_text()) if m.get('model_name')})
context = json.loads((run / 'step-1-round-1/round-1-attempt-1/smoke/context.json').read_text())
faults = [json.loads(line) for line in (root / 'logs/dropped-request.jsonl').read_text().splitlines()]
fault = next(f for f in faults if f['agent_id'] == context['agent_id'])
result = {'run': n, 'symphony_id': sid, 'branch': branch, 'test_exit': test.returncode, 'test_output': test.stdout + test.stderr, 'changed_paths': paths, 'response_models': models, 'fault': fault}
(record / 'independent-result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
assert test.returncode == 0 and 'Ran 3 tests' in test.stderr
assert paths == [f'wc{n}/counter.py', f'wc{n}/test_counter.py']
assert models == ['openai/gpt-4.1-mini']
