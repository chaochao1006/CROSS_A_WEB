"""GitHub Actions / local entry point for the stock monitors."""
import json
import os
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


def run_monitor(snapshot=None):
    snapshot = build_snapshot() if snapshot is None else snapshot
    smc = snapshot.pop('_smc', None)
    save_snapshot(DATA_DIR, snapshot)
    if smc is not None:
        save_snapshot(DATA_DIR/'smc', smc)
        print(f"SMC: {len(smc['triggers'])} triggers")
    print(f"Supertrend: {snapshot['success_count']}/{snapshot['stock_pool_count']} fresh, "
          f"{snapshot['stale_count']} stale, {snapshot['failure_count']} failed, {len(snapshot['triggers'])} triggers")
    if snapshot['success_count']==0:
        raise RuntimeError('全部股票均无新鲜行情，已保存失败状态，请检查网络和数据源')
    return DATA_DIR/'latest.json'


if __name__=='__main__':
    print(run_monitor(build_snapshot(include_smc=True)))
