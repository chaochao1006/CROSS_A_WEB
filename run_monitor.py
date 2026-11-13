"""GitHub Actions / local entry point for the stock monitors."""
import json
import os
from collections import Counter
from pathlib import Path

from super_trend_core import build_snapshot, merge_history

ROOT=Path(__file__).resolve().parent
DATA_DIR=Path(os.environ.get('SUPER_TREND_DATA_DIR',ROOT/'data'))


def save_json(path,payload):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def save_snapshot(folder, snapshot):
    module = snapshot['module']
    events = snapshot.pop('_events')
    path = folder / 'history.json'
    try:
        previous=json.loads(path.read_text(encoding='utf-8'))
        history=previous.get('records',[]) if previous.get('module')==module else []
    except (FileNotFoundError,ValueError,AttributeError):
        history=[]
    history=merge_history(history,events)
    save_json(path,{'module':module,'schema_version':1,'updated_at':snapshot['run_time_cn'],'records':history})
    save_json(folder/'latest.json',snapshot)


def require_fresh_coverage(snapshots, minimum=.9):
    """Persist actual failures, but do not label a nearly empty scan successful."""
    problems = []
    for label, snapshot in snapshots:
        records = snapshot.get('records', [])
        total = snapshot.get('stock_pool_count', len(records))
        fresh = snapshot.get('success_count', sum(r.get('health') == '正常' for r in records))
        errors = Counter(r.get('error', r.get('health', '未知')) for r in records if r.get('health') != '正常')
        print(f'{label}: 新鲜行情 {fresh}/{total}，最低覆盖要求 {minimum:.0%}', flush=True)
        for error, count in errors.most_common(3):
            print(f'  {count}只: {str(error).replace(chr(10), " ")[:350]}', flush=True)
        if not total or fresh / total < minimum:
            problems.append(f'{label}新鲜行情覆盖不足: {fresh}/{total}，要求至少{minimum:.0%}')
    if problems:
        raise RuntimeError('；'.join(problems) + '。真实失败状态已保存，请查看行情错误详情')


def run_monitor(snapshot=None):
    snapshot = build_snapshot() if snapshot is None else snapshot
    smc = snapshot.pop('_smc', None)
    save_snapshot(DATA_DIR, snapshot)
    if smc is not None:
        save_snapshot(DATA_DIR/'smc', smc)
        print(f"SMC: {len(smc['triggers'])} triggers")
    print(f"Supertrend: {snapshot['success_count']}/{snapshot['stock_pool_count']} fresh, "
          f"{snapshot['stale_count']} stale, {snapshot['failure_count']} failed, {len(snapshot['triggers'])} triggers")
    checks = [('Supertrend', snapshot)]
    if smc is not None:
        checks.append(('SMC', smc))
    require_fresh_coverage(checks)
    return DATA_DIR/'latest.json'


if __name__=='__main__':
    print(run_monitor(build_snapshot(include_smc=True)))
