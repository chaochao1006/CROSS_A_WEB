"""Daily Supertrend, using the same SMA-seeded Wilder ATR as the backtest."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
from pathlib import Path
import re
import time

import akshare as ak
import numpy as np
import pandas as pd
import exchange_calendars as xc
import requests

from smc_core import SWING_LENGTH, analyze_smc

ROOT = Path(__file__).resolve().parent
LENGTH, MULTIPLIER = 10, 3.0
SCHEMA_VERSION = 1
START = '2016-01-01'


def load_pool(path=None):
    config = json.loads(Path(path or ROOT/'stock_pool.json').read_text(encoding='utf-8-sig'))
    tickers = list(dict.fromkeys(config['tickers']))
    if not tickers or any(not re.fullmatch(r'\d{6}|\d{5}\.HK', x) for x in tickers):
        raise ValueError('股票池代码须为6位A股或5位.HK港股代码')
    return tickers, config.get('names', {})


def market_of(ticker):
    return 'HK' if ticker.endswith('.HK') else 'A'


def validate_daily(df):
    if df.empty or not df.index.is_unique or not df.index.is_monotonic_increasing:
        raise ValueError('行情为空、日期重复或未排序')
    gaps = df.index.to_series().diff().dt.total_seconds().dropna()/86400
    if len(gaps) and (gaps.median()>4 or (gaps<=4).mean()<.8):
        raise ValueError('数据周期异常，拒绝将周/月/季线当作日线')
    prices = df[['Open','High','Low','Close']]
    if not np.isfinite(prices.to_numpy()).all() or (prices<=0).any().any():
        raise ValueError('行情含非正价格或缺失OHLC')
    if (df.High < prices.max(axis=1)-1e-8).any() or (df.Low > prices.min(axis=1)+1e-8).any():
        raise ValueError('OHLC价格关系异常')


def calculate_supertrend(frame, length=LENGTH, multiplier=MULTIPLIER):
    df = frame.copy().sort_index()
    if len(df)<length:
        raise ValueError(f'不足{length}根完整日线，无法初始化ATR')
    prev = df.Close.shift(1)
    tr = pd.concat([df.High-df.Low,(df.High-prev).abs(),(df.Low-prev).abs()],axis=1).max(axis=1)
    atr = np.full(len(df),np.nan)
    atr[length-1] = tr.iloc[:length].mean()
    for i in range(length,len(df)):
        atr[i] = (atr[i-1]*(length-1)+tr.iloc[i])/length
    upper = (df.High.to_numpy()+df.Low.to_numpy())/2+multiplier*atr
    lower = (df.High.to_numpy()+df.Low.to_numpy())/2-multiplier*atr
    basic_upper,basic_lower = upper.copy(),lower.copy()
    direction,line = np.full(len(df),np.nan),np.full(len(df),np.nan)
    first = length-1
    direction[first],line[first] = -1,upper[first]
    close = df.Close.to_numpy()
    for i in range(length,len(df)):
        upper[i] = basic_upper[i] if basic_upper[i]<upper[i-1] or close[i-1]>upper[i-1] else upper[i-1]
        lower[i] = basic_lower[i] if basic_lower[i]>lower[i-1] or close[i-1]<lower[i-1] else lower[i-1]
        if line[i-1]==upper[i-1]:
            direction[i] = 1 if close[i]>upper[i] else -1
        else:
            direction[i] = -1 if close[i]<lower[i] else 1
        line[i] = lower[i] if direction[i]==1 else upper[i]
    df['atr'],df['direction'],df['supertrend'] = atr,direction,line
    df['event'] = np.where((df.direction==1)&(df.direction.shift(1)==-1),'买入',
                           np.where((df.direction==-1)&(df.direction.shift(1)==1),'卖出',''))
    return df.dropna(subset=['supertrend'])


@lru_cache(maxsize=1)
def a_trade_dates():
    frame = ak.tool_trade_date_hist_sina()
    dates = pd.DatetimeIndex(pd.to_datetime(frame['trade_date'])).sort_values().normalize()
    if not len(dates):
        raise ValueError('A股交易日历为空')
    return dates


def session_context(market, now=None):
    now = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz='Asia/Shanghai'))
    if now.tzinfo is None:
        raise ValueError('now须包含时区')
    local = now.tz_convert('Asia/Shanghai')
    if market=='A':
        dates = a_trade_dates()
        today = local.normalize().tz_localize(None)
        if dates[-1]<today:
            raise ValueError('A股交易日历覆盖不足，拒绝猜测节假日')
        cutoff = today if local.hour*60+local.minute>=15*60+15 else today-pd.Timedelta(days=1)
        closed = dates[dates<=cutoff]
        future = dates[dates>closed[-1]]
        return closed[-1].strftime('%Y-%m-%d'),future[0].strftime('%Y-%m-%d') if len(future) else ''
    # XHKG includes half-day sessions; allow 10 minutes for the closing auction,
    # then 15 minutes for the daily data source to settle.
    begin,end=(local-pd.Timedelta(days=40)).date(),(local+pd.Timedelta(days=20)).date()
    schedule = xc.get_calendar('XHKG',start=begin,end=end).schedule
    closed = schedule[schedule['close']+pd.Timedelta(minutes=25)<=now.tz_convert('UTC')]
    if closed.empty:
        raise ValueError('港股日历无已收盘交易日')
    last = closed.index[-1]
    future = schedule.index[schedule.index>last]
    return last.strftime('%Y-%m-%d'),future[0].strftime('%Y-%m-%d') if len(future) else ''


def normalize(frame, expected):
    df = frame.rename(columns={'日期':'date','Date':'date','开盘':'Open','最高':'High','最低':'Low','收盘':'Close','成交量':'Volume',
                              'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'}).copy()
    if 'date' in df.columns:
        df = df.set_index('date')
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert('Asia/Shanghai').tz_localize(None)
    df.index = df.index.normalize()
    df = df[['Open','High','Low','Close','Volume']].apply(pd.to_numeric,errors='coerce').sort_index().loc[START:expected]
    return df


def yahoo_hk(ticker, expected):
    symbol = f"{int(ticker.split('.')[0]):04d}.HK"
    params = {'period1':int(pd.Timestamp(START,tz='Asia/Hong_Kong').timestamp()),
              'period2':int((pd.Timestamp(expected,tz='Asia/Hong_Kong')+pd.Timedelta(days=1)).timestamp()),
              'interval':'1d','includeAdjustedClose':'true','events':'history'}
    errors=[]
    for host in ['query1.finance.yahoo.com','query2.finance.yahoo.com']:
        try:
            response=requests.get(f'https://{host}/v8/finance/chart/{symbol}',params=params,headers={'User-Agent':'Mozilla/5.0'},timeout=20)
            response.raise_for_status()
            item=response.json()['chart']['result'][0]
            if item['meta'].get('dataGranularity')!='1d':
                raise ValueError('Yahoo返回非日线')
            dates=pd.to_datetime(item['timestamp'],unit='s',utc=True).tz_convert('Asia/Hong_Kong').tz_localize(None).normalize()
            df=pd.DataFrame(item['indicators']['quote'][0],index=dates).rename(columns=str.capitalize)
            adjusted=np.array(item['indicators']['adjclose'][0]['adjclose'],dtype=float)
            factor=adjusted/df.Close.to_numpy()
            for col in ['Open','High','Low','Close']:
                df[col]*=factor
            df=normalize(df,expected)
            validate_daily(df)
            return df,f'Yahoo {host} verified 1d, adjusted','前复权'
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError('；'.join(errors))


def fetch_daily(ticker, expected):
    errors=[]
    for attempt in range(2):
        try:
            hk=market_of(ticker)=='HK'
            history=ak.stock_hk_hist if hk else ak.stock_zh_a_hist
            params={'symbol':ticker.split('.')[0],'period':'daily','start_date':'20160101','end_date':expected.replace('-','')}
            if not hk:
                params['timeout']=20
            raw=history(**params,adjust='qfq')
            df=normalize(raw,expected)
            note='前复权'
            if (df[['Open','High','Low','Close']]<=0).any().any():
                df=normalize(history(**params,adjust='hfq'),expected)
                # Constant rescaling keeps the backward-adjusted trend unchanged while making latest prices readable.
                raw_last=normalize(history(**{**params,'start_date':expected.replace('-','')},adjust=''),expected)
                if raw_last.empty or df.empty or df.index[-1]!=raw_last.index[-1]:
                    raise ValueError('后复权行情缺少可对齐的最新原始报价')
                scale=float(raw_last.iloc[-1].Close/df.iloc[-1].Close)
                df[['Open','High','Low','Close']]*=scale
                note='早期前复权含非正值；改用后复权并归一至最新报价'
            validate_daily(df)
            return df,'AKShare / 东方财富 daily',note
        except Exception as exc:
            errors.append(str(exc))
            if attempt==0:
                time.sleep(1)
    if market_of(ticker)=='HK':
        try:
            return yahoo_hk(ticker,expected)
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError('；'.join(errors))


def completed_prices(ticker, expected):
    df,source,note=fetch_daily(ticker,expected)
    df=df.loc[START:expected].copy()
    validate_daily(df)
    return df, source, note


def analyze(ticker, name, expected, execution_date):
    return analyze_supertrend(*completed_prices(ticker, expected), ticker, name, expected, execution_date)


def analyze_supertrend(df, source, note, ticker, name, expected, execution_date):
    bars=len(df)
    df=calculate_supertrend(df)
    latest=df.iloc[-1]
    data_date=str(df.index[-1].date())
    health='正常' if data_date==expected else '行情过期/停牌'
    flips=df[df.event!='']
    last_event=flips.iloc[-1].event if len(flips) else ''
    last_date=str(flips.index[-1].date()) if len(flips) else ''
    record={'ticker':ticker,'company_name':name,'market':market_of(ticker),'data_date':data_date,'expected_date':expected,
            'state':'持有' if latest.direction==1 else '观望','event':latest.event if health=='正常' else '',
            'close':float(latest.Close),'supertrend':float(latest.supertrend),'last_event':last_event,'last_event_date':last_date,
            'execution_date':execution_date,'health':health,'data_interval':'1d','daily_bar_count':bars,
            'data_source':source,'adjustment_note':note,'history_start':str(df.index[0].date())}
    events=[{'ticker':ticker,'company_name':name,'market':market_of(ticker),'data_date':str(day.date()),
             'signal':row.event,'close':float(row.Close),'supertrend':float(row.supertrend)} for day,row in flips.iterrows()]
    return record,events


def build_snapshot(tickers=None,names=None,now=None,*,include_smc=False):
    if tickers is None:
        tickers,names=load_pool()
    names=names or {}
    now=pd.Timestamp(now if now is not None else pd.Timestamp.now(tz='Asia/Shanghai'))
    contexts,calendar_errors={},{}
    for market in sorted({market_of(ticker) for ticker in tickers}):
        try:
            contexts[market]=session_context(market,now)
        except Exception as exc:
            calendar_errors[market]=str(exc)
    def worker(ticker):
        name=names.get(ticker,ticker)
        market=market_of(ticker)
        base={'ticker':ticker,'company_name':name,'market':market}
        try:
            if market in calendar_errors:
                raise ValueError(calendar_errors[market])
            expected,execution=contexts[market]
            prices=completed_prices(ticker,expected)
        except Exception as exc:
            failed={**base,'health':'更新失败','error':str(exc)}
            return ({**failed,'state':None,'event':''},[]),(failed,[])
        try:
            st_result=analyze_supertrend(*prices,ticker,name,expected,execution)
        except Exception as exc:
            st_result=({**base,'state':None,'event':'','health':'更新失败','error':str(exc)},[])
        smc_result=(None,[])
        if include_smc:
            try:
                smc_result=analyze_smc(prices[0],ticker,name,market,expected)
            except Exception as exc:
                smc_result=({**base,'health':'更新失败','error':str(exc)},[])
        return st_result,smc_result
    records,events,smc_records,smc_events=[],[],[],[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        for (row,history),(smc_row,smc_history) in executor.map(worker,tickers):
            records.append(row);events.extend(history)
            if include_smc:
                smc_records.append(smc_row)
                smc_events.extend(smc_history)
    triggers=[dict(r,signal=r['event']) for r in records if r['health']=='正常' and r['event'] in ('买入','卖出')]
    snapshot={'module':'super-trend','schema_version':SCHEMA_VERSION,'data_interval':'1d',
            'strategy':{'atr_length':LENGTH,'multiplier':MULTIPLIER,'signal':'收盘确认，下一交易日开盘执行'},
            'run_time_cn':now.tz_convert('Asia/Shanghai').isoformat(),'market_dates':{k:v[0] for k,v in contexts.items()},
            'stock_pool_count':len(tickers),'success_count':sum(r['health']=='正常' for r in records),
            'failure_count':sum(r['health']=='更新失败' for r in records),
            'stale_count':sum(r['health']=='行情过期/停牌' for r in records),
            'triggers':triggers,'records':records,'_events':events}
    if include_smc:
        snapshot['_smc']={
            'module':'smc','schema_version':1,'data_interval':'1d','swing_length':SWING_LENGTH,
            'run_time_cn':snapshot['run_time_cn'],'market_dates':snapshot['market_dates'],
            'records':smc_records,
            'triggers':[event for event in smc_events if event['data_date']==contexts[event['market']][0]],
            '_events':smc_events,
        }
    return snapshot


def merge_history(previous,events):
    rows={(r['ticker'],r['data_date'],r['signal']):r for r in previous+events}
    return sorted(rows.values(),key=lambda r:(r['data_date'],r['ticker'],r['signal']),reverse=True)[:1000]
