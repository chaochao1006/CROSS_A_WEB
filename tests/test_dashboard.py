import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'streamlit_app.py'


class DashboardTests(unittest.TestCase):
    def test_old_snapshot_is_not_shown_as_supertrend(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'SUPER_TREND_DATA_DIR':folder}):
            (Path(folder)/'latest.json').write_text(json.dumps({'app':'A-CROSS','triggered':[{'ticker':'000977'}]}),encoding='utf-8')
            app=AppTest.from_file(str(APP)).run(timeout=15)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.subheader),0)
            self.assertIn('首次Supertrend',app.info[0].value)

    def test_triggers_and_two_state_tables_exclude_errors(self):
        base={'ticker':'000977','company_name':'浪潮信息','market':'A','data_date':'2026-11-02','close':54.26,'supertrend':61.2,'health':'正常'}
        snapshot={'module':'super-trend','schema_version':1,'data_interval':'1d','stock_pool_count':3,
                  'run_time_cn':'2026-11-03T10:00:00+08:00','market_dates':{'A':'2026-11-02'},
                  'records':[{**base,'state':'持有'},{**base,'ticker':'603629','state':'观望'},
                             {**base,'ticker':'600183','state':None,'health':'更新失败','error':'offline'}],
                  'triggers':[{**base,'signal':'买入','execution_date':'2026-11-03'}]}
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'SUPER_TREND_DATA_DIR':folder}):
            (Path(folder)/'latest.json').write_text(json.dumps(snapshot),encoding='utf-8')
            app=AppTest.from_file(str(APP)).run(timeout=15)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.subheader),3)
            self.assertEqual(app.subheader[0].value,'当日触发记录')
            self.assertIn('持有（1只）',app.subheader[1].value)
            self.assertIn('观望（1只）',app.subheader[2].value)
            self.assertEqual(app.dataframe[0].value.iloc[0]['触发信号'],'买入')
            self.assertEqual(app.dataframe[1].value.iloc[0]['代码'],'000977')
            self.assertEqual(app.dataframe[2].value.iloc[0]['代码'],'603629')


if __name__=='__main__':
    unittest.main()
