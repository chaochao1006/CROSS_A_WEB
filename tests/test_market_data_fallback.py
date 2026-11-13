import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

import market_data_fallback as fallback
import super_trend_core as core
from run_monitor import require_fresh_coverage


class MarketDataFallbackTests(unittest.TestCase):
    def response(self, rows, adjustment='hfq'):
        response = Mock()
        response.json.return_value = {'code': 0, 'data': {'sz000977': {f'{adjustment}day': rows}}}
        return response

    def test_full_range_chunks_are_disjoint_and_scaled_to_raw_close(self):
        first = self.response([
            ['2015-12-31', '100', '100', '101', '99', '10'],
            ['2016-01-04', '100', '100', '101', '99', '10'],
            ['2017-12-29', '200', '200', '201', '199', '20'],
        ])
        second = self.response([
            ['2017-12-29', '200', '200', '201', '199', '20'],
            ['2018-01-02', '200', '200', '201', '199', '20'],
            ['2019-12-30', '300', '300', '301', '299', '30'],
            ['2020-01-02', '400', '400', '401', '399', '40'],
        ])
        raw = self.response([['2019-12-30', '30', '30', '30.1', '29.9', '30']], '')
        with patch.object(fallback.requests, 'get', side_effect=[first, second, raw]) as get:
            result, source, note = fallback.tencent_a_daily('000977', '2019-12-30')
        self.assertEqual(len(result), 4)
        self.assertEqual(result.index[0], pd.Timestamp('2016-01-04'))
        self.assertEqual(result.index[-1], pd.Timestamp('2019-12-30'))
        self.assertTrue(result.index.is_unique)
        self.assertAlmostEqual(result.Close.iloc[0], 10.)
        self.assertAlmostEqual(result.Close.iloc[-1], 30.)
        self.assertIn('后复权', note)
        self.assertIn('腾讯', source)
        self.assertIn('2016-01-01,2017-12-31,640,hfq', get.call_args_list[0].kwargs['params']['param'])
        self.assertIn('2018-01-01,2019-12-30,640,hfq', get.call_args_list[1].kwargs['params']['param'])
        self.assertEqual(get.call_count, 3)

    def test_network_failure_has_bounded_retry_and_timeout(self):
        with patch.object(fallback.requests, 'get', side_effect=requests.ConnectionError('offline')) as get, \
                patch.object(fallback.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, '腾讯日线获取失败'):
                fallback._daily_block('sz000977', '2026-01-01', '2026-11-12', 'hfq')
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(call.kwargs['timeout'] == 20 for call in get.call_args_list))

    def test_eastmoney_failure_uses_validated_backup(self):
        index = pd.bdate_range('2026-10-01', periods=30)
        frame = pd.DataFrame({'Open': 10., 'High': 11., 'Low': 9., 'Close': 10., 'Volume': 100.}, index=index)
        expected = str(index[-1].date())
        with patch.object(core.ak, 'stock_zh_a_hist', side_effect=ConnectionError('blocked')), \
                patch.object(core.time, 'sleep'), \
                patch.object(core, 'tencent_a_daily', return_value=(frame, 'Tencent', 'hfq')) as backup:
            result, source, _ = core.fetch_daily('000977', expected)
        self.assertEqual(source, 'Tencent')
        backup.assert_called_once_with('000977', expected, core.START)
        pd.testing.assert_frame_equal(result, frame)

    def test_backup_does_not_turn_stale_prices_into_fresh_signals(self):
        index = pd.bdate_range('2026-10-01', periods=30)
        frame = pd.DataFrame({'Open': 10., 'High': 11., 'Low': 9., 'Close': 10., 'Volume': 100.}, index=index)
        with patch.object(core, 'fetch_daily', return_value=(frame, 'Tencent', 'hfq')):
            row, _ = core.analyze('000977', '浪潮信息', '2026-12-01', '2026-12-02')
        self.assertEqual(row['health'], '行情过期/停牌')
        self.assertEqual(row['event'], '')

    def test_only_five_fresh_of_621_is_a_failed_scan(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, '5/621'):
                require_fresh_coverage([('SMC-选', {'stock_pool_count': 621, 'success_count': 5})])
            require_fresh_coverage([('SMC-选', {'stock_pool_count': 621, 'success_count': 620})])


if __name__ == '__main__':
    unittest.main()
