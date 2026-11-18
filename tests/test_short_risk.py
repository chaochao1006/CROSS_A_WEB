import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

import run_short_risk as monitor
from run_monitor import save_snapshot
from short_risk_core import (ShortRiskResult, is_short_rebound,
                             risk_level_from_score, score_short_rebound_risk)


class ShortRiskTests(unittest.TestCase):
    def indicators(self, points=6):
        row = {'Open':100., 'High':101., 'Low':99., 'Close':100., 'Volume':1000.,
               'MA5':80., 'MA10':80., 'MA20':80., 'MA50':80., 'Deviation20':16.,
               'RSI6':86., 'RSI12':76., 'K':50., 'D':50., 'J':50.,
               'Return_5D':0., 'Return_10D':0., 'Volume_Ratio':1.}
        data = pd.DataFrame([row] * 60, index=pd.bdate_range('2026-08-26', periods=60))
        if points == 7:
            data['K'] = data['D'] = 81.
        return data

    def test_exact_six_seven_boundary_and_rebound_gate(self):
        for points in (6, 7):
            data = self.indicators(points)
            result = ShortRiskResult('000977')
            self.assertEqual(is_short_rebound(data)[0], 4)
            self.assertEqual(score_short_rebound_risk(data, result), points)
            self.assertEqual(risk_level_from_score(points), '短线过热，容易回踩')
            with patch.object(monitor, 'calculate_indicators', return_value=data):
                record = monitor.analyze_prices(data, '000977', '浪潮信息', str(data.index[-1].date()))
            self.assertEqual(record['short_risk_score'], points)
        data = self.indicators(7)
        data['Close'] = 10.
        with patch.object(monitor, 'calculate_indicators', return_value=data):
            record = monitor.analyze_prices(data, '000977', '', str(data.index[-1].date()))
        self.assertEqual(record['short_risk_score'], 0)
        self.assertLess(record['rebound_score'], 4)

    def test_freshness_threshold_live_exclusion_and_history_dedup(self):
        data = self.indicators()
        expected = str(data.index[-1].date())
        rows = [
            {'ticker':'000977', 'health':'正常', 'short_risk_score':6, 'data_date':expected},
            {'ticker':'002015', 'health':'正常', 'short_risk_score':7, 'data_date':expected},
            {'ticker':'600483', 'health':'行情过期/停牌', 'short_risk_score':9, 'data_date':'2026-01-01'},
        ]
        with patch.object(monitor, 'load_pool', return_value=([r['ticker'] for r in rows], {})), \
             patch.object(monitor, 'session_context', return_value=(expected, '2026-12-01')), \
             patch.object(monitor, 'completed_prices', return_value=(data, 'fixture', '前复权')), \
             patch.object(monitor, 'analyze_prices', side_effect=lambda frame, ticker, *args: next(r for r in rows if r['ticker']==ticker)):
            snapshot = monitor.build_snapshot(max_workers=1)
        self.assertEqual([r['ticker'] for r in snapshot['triggers']], ['002015'])
        with tempfile.TemporaryDirectory() as folder:
            save_snapshot(Path(folder), json.loads(json.dumps(snapshot)))
            save_snapshot(Path(folder), json.loads(json.dumps(snapshot)))
            history = json.loads((Path(folder)/'history.json').read_text(encoding='utf-8'))
            self.assertEqual(len(history['records']), 1)
        live = data.copy()
        live.loc[data.index[-1]+pd.offsets.BDay()] = data.iloc[-1]
        with patch.object(monitor, 'calculate_indicators', side_effect=lambda frame: frame):
            record = monitor.analyze_prices(live, '000977', '', expected)
        self.assertEqual(record['data_date'], expected)
        self.assertEqual(record['daily_bar_count'], 60)
        with self.assertRaisesRegex(ValueError, '至少需要60日'):
            monitor.analyze_prices(data.iloc[:59], '000977', '', expected)

    def test_dashboard_and_exact_pool(self):
        tickers, names = monitor.load_pool(monitor.ROOT/'short_risk_pool.json')
        self.assertEqual(tickers, ['000977','002015','600483','000921','600619','000543'])
        self.assertEqual(len(names), 6)
        row = {'ticker':'000977', 'company_name':'浪潮信息', 'data_date':'2026-11-17',
               'health':'正常', 'rebound_state':'短线反弹确认', 'rebound_score':6,
               'short_risk_score':7, 'risk_level':'短线过热，容易回踩', 'risk_sources':['偏离MA20超过15%']}
        snapshot = {'module':'short-risk','schema_version':1,'data_interval':'1d',
                    'market_dates':{'A':'2026-11-17'},'run_time_cn':'2026-11-18T10:00:00+08:00',
                    'success_count':1,'records':[row],'triggers':[row]}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'SUPER_TREND_DATA_DIR':folder}):
            dest = Path(folder)/'short-risk'
            dest.mkdir()
            (dest/'latest.json').write_text(json.dumps(snapshot), encoding='utf-8')
            app = AppTest.from_file(str(monitor.ROOT/'streamlit_app.py')).run(timeout=20)
            app.sidebar.radio[0].set_value('短线风险').run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(app.subheader[0].value, '当日触发记录')
            self.assertEqual(app.dataframe[0].value.iloc[0]['代码'], '000977')
            self.assertEqual(app.dataframe[0].value.iloc[0]['风险分'], 7)


if __name__ == '__main__':
    unittest.main()
