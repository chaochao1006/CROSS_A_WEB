"""GitHub Actions / local entry point for the Supertrend-only monitor."""
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


def run_monitor():
    snapshot=build_snapshot()
    events=snapshot.pop('_events')
    path=DATA_DIR/'history.json'
    try:
        previous=json.loads(path.read_text(encoding='utf-8'))
        history=previous.get('records',[]) if previous.get('module')=='super-trend' else []
    except (FileNotFoundError,ValueError,AttributeError):
        history=[]
    history=merge_history(history,events)
    save_json(path,{'module':'super-trend','schema_version':1,'updated_at':snapshot['run_time_cn'],'records':history})
    save_json(DATA_DIR/'latest.json',snapshot)
    print(f"Supertrend: {snapshot['success_count']}/{snapshot['stock_pool_count']} fresh, "
          f"{snapshot['stale_count']} stale, {snapshot['failure_count']} failed, {len(snapshot['triggers'])} triggers")
    if snapshot['success_count']==0:
        raise RuntimeError('全部股票均无新鲜行情，已保存失败状态，请检查网络和数据源')
    return DATA_DIR/'latest.json'


if __name__=='__main__':
    print(run_monitor())
