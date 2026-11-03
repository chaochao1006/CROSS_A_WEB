import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import super_trend_core as core
import run_monitor as runner


class SupertrendTests(unittest.TestCase):
    def prices(self):
        close=np.r_[np.full(10,100.),110.,90.,np.full(10,95.)]
        return pd.DataFrame({'Open':close,'High':close+1,'Low':close-1,'Close':close,'Volume':1000},index=pd.bdate_range('2026-10-01',periods=len(close)))

    def test_manual_atr_and_exact_flips(self):
        data=core.calculate_supertrend(self.prices())
        self.assertEqual(data.iloc[0].atr,2.)
        self.assertEqual(data.iloc[0].supertrend,106.)
        self.assertEqual(data.iloc[0].direction,-1)
        self.assertAlmostEqual(data.iloc[1].atr,2.9)
        self.assertAlmostEqual(data.iloc[1].supertrend,101.3)
        self.assertEqual(data.iloc[1].event,'买入')
        self.assertAlmostEqual(data.iloc[2].atr,4.71)
        self.assertAlmostEqual(data.iloc[2].supertrend,104.13)
        self.assertEqual(data.iloc[2].event,'卖出')

    def test_prefix_invariance(self):
        frame=self.prices()
        result=core.calculate_supertrend(frame)
        for count in range(10,len(frame)):
            pd.testing.assert_frame_equal(core.calculate_supertrend(frame.iloc[:count]),result.loc[:frame.index[count-1]])

    def test_bad_periods_and_prices_are_rejected(self):
        frame=self.prices()
        frame.index=pd.date_range('2020-01-01',periods=len(frame),freq='QS')
        with self.assertRaisesRegex(ValueError,'周期异常'):
            core.validate_daily(frame)
        frame=self.prices();frame.iloc[0,frame.columns.get_loc('Low')]=-1
        with self.assertRaisesRegex(ValueError,'非正价格'):
            core.validate_daily(frame)

    def test_a_calendar_before_after_close_and_holiday(self):
        dates=pd.to_datetime(['2026-09-30','2026-10-09','2026-11-02','2026-11-03','2026-11-04'])
        with patch.object(core,'a_trade_dates',return_value=dates):
            self.assertEqual(core.session_context('A','2026-11-03T10:00:00+08:00'),('2026-11-02','2026-11-03'))
            self.assertEqual(core.session_context('A','2026-11-03T15:16:00+08:00'),('2026-11-03','2026-11-04'))
            self.assertEqual(core.session_context('A','2026-10-01T18:00:00+08:00'),('2026-09-30','2026-10-09'))

    def test_hk_half_day_and_holiday(self):
        self.assertEqual(core.session_context('HK','2025-12-24T12:00:00+08:00')[0],'2025-12-23')
        self.assertEqual(core.session_context('HK','2025-12-24T12:16:00+08:00')[0],'2025-12-23')
        self.assertEqual(core.session_context('HK','2025-12-24T12:26:00+08:00')[0],'2025-12-24')
        self.assertEqual(core.session_context('HK','2025-12-25T18:00:00+08:00')[0],'2025-12-24')

    def test_live_bars_excluded_and_one_day_trigger(self):
        frame=self.prices()
        expected=str(frame.index[10].date())
        with patch.object(core,'fetch_daily',return_value=(frame,'fixture','前复权')):
            row,_=core.analyze('TEST','测试',expected,'2026-10-20')
            self.assertEqual(row['data_date'],expected)
            self.assertEqual(row['event'],'买入')
            self.assertEqual(row['state'],'持有')
            expected=str(frame.index[12].date())
            row,_=core.analyze('TEST','测试',expected,'2026-10-22')
            self.assertEqual(row['event'],'')
            self.assertEqual(row['state'],'观望')

    def test_stale_and_failures_do_not_trigger(self):
        frame=self.prices()
        future=str((frame.index[-1]+pd.Timedelta(days=1)).date())
        with patch.object(core,'session_context',return_value=(future,'2026-12-01')),patch.object(core,'fetch_daily',return_value=(frame,'fixture','前复权')):
            data=core.build_snapshot(['TEST'],{},now='2026-11-03T10:00:00+08:00')
        self.assertEqual(data['stale_count'],1)
        self.assertEqual(data['triggers'],[])
        with patch.object(core,'session_context',return_value=(future,'2026-12-01')),patch.object(core,'fetch_daily',side_effect=ValueError('offline')):
            data=core.build_snapshot(['TEST'],{},now='2026-11-03T10:00:00+08:00')
        self.assertEqual(data['failure_count'],1)
        self.assertIsNone(data['records'][0]['state'])
        json.dumps(data,allow_nan=False)

    def test_short_history_has_explicit_failure(self):
        with self.assertRaisesRegex(ValueError,'不足10根'):
            core.calculate_supertrend(self.prices().iloc[:9])

    def test_history_idempotence_and_direction_key(self):
        event={'ticker':'000977','data_date':'2026-11-02','signal':'买入'}
        initial=core.merge_history([], [event])
        self.assertEqual(core.merge_history(initial,[event]),initial)
        self.assertEqual(len(core.merge_history(initial,[{**event,'signal':'卖出'}])),2)

    def test_pool_can_be_reduced_without_code_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'pool.json'
            path.write_text(json.dumps({'tickers':['000977','02476.HK','000977'],'names':{'000977':'浪潮信息'}}),encoding='utf-8')
            tickers,names=core.load_pool(path)
            self.assertEqual(tickers,['000977','02476.HK'])
            self.assertEqual(names['000977'],'浪潮信息')

    def test_old_history_replaced_and_snapshot_repeatable(self):
        snapshot={'module':'super-trend','stock_pool_count':1,'success_count':1,'failure_count':0,'stale_count':0,
                  'triggers':[],'run_time_cn':'2026-11-03T10:00:00+08:00','_events':[{'ticker':'000977','data_date':'2026-11-02','signal':'卖出'}]}
        with tempfile.TemporaryDirectory() as folder,patch.object(runner,'DATA_DIR',Path(folder)),patch.object(runner,'build_snapshot',side_effect=lambda:json.loads(json.dumps(snapshot))):
            path=Path(folder)/'history.json'
            path.write_text(json.dumps({'records':[{'data_day':'old','total_score':90}]}),encoding='utf-8')
            runner.run_monitor();runner.run_monitor()
            history=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(len(history['records']),1)
            self.assertEqual(history['module'],'super-trend')


if __name__=='__main__':
    unittest.main()
