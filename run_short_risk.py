"""A-share short-risk monitor, using completed daily prices and the US scoring rules."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pandas as pd

from run_monitor import DATA_DIR, ROOT, save_snapshot, require_fresh_coverage
from super_trend_core import completed_prices, load_pool, session_context
from short_risk_core import (ShortRiskResult, TRIGGER_SCORE, calculate_indicators,
                             is_short_rebound, risk_level_from_score, safe_float,
                             score_short_rebound_risk)


def analyze_prices(frame, ticker, name, expected, source='', note=''):
    frame = frame.loc[:expected].copy()
    # Match the original monitor's 18-month indicator lookback.
    frame = frame.loc[pd.Timestamp(expected) - pd.DateOffset(months=18):]
    base = {'ticker': ticker, 'company_name': name, 'market': 'A', 'expected_date': expected,
            'data_source': source, 'adjustment_note': note, 'daily_bar_count': len(frame)}
    if len(frame) < 60:
        raise ValueError(f'有效数据过短：{len(frame)}个交易日，至少需要60日')
    frame = calculate_indicators(frame)
    latest = frame.iloc[-1]
    result = ShortRiskResult(ticker=ticker)
    result.rebound_score, result.rebound_state, result.rebound_reasons = is_short_rebound(frame)
    if result.rebound_score < 4:
        result.risk_level = '未形成短线反弹，不进入过热评分'
        result.risk_sources = ['未满足短线反弹过滤条件']
    else:
        result.short_risk_score = score_short_rebound_risk(frame, result)
        result.risk_level = risk_level_from_score(result.short_risk_score)
    for attr, column in {'close':'Close', 'ma5':'MA5', 'ma10':'MA10', 'ma20':'MA20',
                         'ma50':'MA50', 'rsi6':'RSI6', 'rsi12':'RSI12', 'k':'K', 'd':'D',
                         'j':'J', 'deviation20':'Deviation20', 'return5':'Return_5D',
                         'return10':'Return_10D', 'volume_ratio':'Volume_Ratio'}.items():
        setattr(result, attr, safe_float(latest[column]))
    day = str(frame.index[-1].date())
    return {**asdict(result), **base, 'data_date': day,
            'health': '正常' if day == expected else '行情过期/停牌',
            'data_warning': f'历史数据偏短：{len(frame)}个交易日' if len(frame) < 120 else ''}


def build_snapshot(now=None, max_workers=3):
    tickers, names = load_pool(ROOT / 'short_risk_pool.json')
    now = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz='Asia/Shanghai'))
    try:
        expected, _ = session_context('A', now)
        calendar_error = ''
    except Exception as exc:
        expected, calendar_error = '', str(exc)

    def worker(ticker):
        name = names.get(ticker, ticker)
        try:
            if calendar_error:
                raise ValueError(calendar_error)
            frame, source, note = completed_prices(ticker, expected)
            return analyze_prices(frame, ticker, name, expected, source, note)
        except Exception as exc:
            return {'ticker': ticker, 'company_name': name, 'market': 'A',
                    'health': '更新失败', 'error': str(exc)}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        records = list(executor.map(worker, tickers))
    records.sort(key=lambda row: (row.get('health') != '正常',
                                 -row.get('short_risk_score', 0), row['ticker']))
    events = [dict(row, signal='短线风险提醒') for row in records
              if row['health'] == '正常' and row['short_risk_score'] > TRIGGER_SCORE]
    return {'module': 'short-risk', 'schema_version': 1, 'data_interval': '1d',
            'run_time_cn': now.tz_convert('Asia/Shanghai').isoformat(),
            'market_dates': {'A': expected} if expected else {}, 'stock_pool_count': len(tickers),
            'success_count': sum(r['health'] == '正常' for r in records),
            'failure_count': sum(r['health'] == '更新失败' for r in records),
            'stale_count': sum(r['health'] == '行情过期/停牌' for r in records),
            'trigger_rule': '反弹确认分至少4分，风险分大于6分（至少7分）',
            'records': records, 'triggers': events, '_events': events}


def main():
    snapshot = build_snapshot()
    save_snapshot(DATA_DIR / 'short-risk', snapshot)
    print(f"短线风险：{snapshot['success_count']}/{snapshot['stock_pool_count']} 行情正常，"
          f"{len(snapshot['triggers'])} 个触发", flush=True)
    require_fresh_coverage([('短线风险', snapshot)])


if __name__ == '__main__':
    main()
