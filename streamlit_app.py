"""Daily Supertrend and SMC dashboard."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parent
DATA_DIR=Path(os.environ.get('SUPER_TREND_DATA_DIR',ROOT/'data'))


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return {}


def table(records,events=False):
    rows=[]
    for item in records:
        row={'代码':item['ticker'],'名称':item.get('company_name',''),'市场':item.get('market',''),
             '行情日期':item.get('data_date',''),'收盘价':item.get('close'),'Supertrend线':item.get('supertrend')}
        if events:
            row['触发信号']=item.get('signal',item.get('event',''))
            if item.get('execution_date'):
                row['计划执行日']=item['execution_date']
        else:
            row.update({'当前信号':item.get('state'),'最近触发日':item.get('last_event_date',''),'最近触发':item.get('last_event','')})
        rows.append(row)
    return pd.DataFrame(rows)


def render_smc(module, title):
    st.title(f'{title} 股票监控')
    folder = DATA_DIR / module
    latest = load_json(folder/'latest.json')
    if latest.get('module') != module or latest.get('schema_version') != 1 or latest.get('data_interval') != '1d':
        st.info(f'等待首次 {title} 数据更新。可运行 GitHub Actions 中的 Supertrend Monitor。')
        return
    st.caption(f"日线 Swing 长度 {latest['swing_length']} · 收盘确认绿色 Swing BOS 或 CHoCH")
    dates = ' ｜ '.join(f"{'A股' if market == 'A' else '港股'} {day}" for market, day in latest['market_dates'].items())
    st.caption(f"快照交易日 {dates} ｜ 北京时间更新于 {latest['run_time_cn']}")
    records = latest['records']
    fresh = sum(row['health'] == '正常' for row in records)
    st.caption(f"股票池 {len(records)} 只 ｜ 正常 {fresh} 只 ｜ 行情异常或不足 {len(records) - fresh} 只")
    labels = {'ticker':'代码','company_name':'名称','market':'市场','data_date':'行情日期',
              'signal':'触发信号','close':'复权收盘价','level':'突破结构价位','health':'数据状态',
              'last_event':'最近触发','last_event_date':'最近触发日','error':'原因'}
    event_columns = ['ticker','company_name','market','data_date','signal','close','level']
    st.subheader('当日触发记录')
    if latest['triggers']:
        st.dataframe(pd.DataFrame(latest['triggers']).reindex(columns=event_columns).rename(columns=labels),
                     width='stretch',hide_index=True)
    elif fresh:
        st.info('行情正常的股票中，快照交易日无绿色 Swing BOS 或 CHoCH。')
    else:
        st.warning('本次没有可确认的日线行情。')
    with st.expander('股票池与数据状态'):
        columns = ['ticker','company_name','market','data_date','health','last_event','last_event_date','error']
        st.dataframe(pd.DataFrame(records).reindex(columns=columns).rename(columns=labels),
                     width='stretch',hide_index=True)
    with st.expander('历史触发'):
        history = load_json(folder/'history.json')
        if history.get('module') == module and history.get('records'):
            st.dataframe(pd.DataFrame(history['records']).reindex(columns=event_columns).rename(columns=labels),
                         width='stretch',hide_index=True)
        else:
            st.info('暂无历史触发。')


st.set_page_config(page_title='股票监控',page_icon='📈',layout='wide')
module = st.sidebar.radio('监控模块', ['Supertrend', 'SMC', 'SMC-选'])
if module in ('SMC', 'SMC-选'):
    if st.button('刷新数据'):
        st.rerun()
    render_smc('smc' if module == 'SMC' else 'smc-selected', module)
    st.stop()
st.title('Supertrend 股票监控')
st.caption('日线 ATR(10) × 3 · 收盘确认信号 · 下一交易日开盘执行')
if st.button('刷新数据',help='重新读取已生成的监控结果；行情由GitHub Actions更新。'):
    st.rerun()
latest=load_json(DATA_DIR/'latest.json')
if latest.get('module')!='super-trend' or latest.get('schema_version')!=1 or latest.get('data_interval')!='1d':
    st.info('等待首次Supertrend数据更新。请运行GitHub Actions中的Supertrend Monitor。')
    st.stop()
records=latest.get('records',[])
fresh=[r for r in records if r.get('health')=='正常']
holds=[r for r in fresh if r.get('state')=='持有']
waits=[r for r in fresh if r.get('state')=='观望']
problems=[r for r in records if r.get('health')!='正常']
cols=st.columns(6)
for col,(label,value) in zip(cols,[('股票池',latest.get('stock_pool_count',0)),('正常更新',len(fresh)),('当日触发',len(latest.get('triggers',[]))),('持有',len(holds)),('观望',len(waits)),('异常/过期',len(problems))]):
    col.metric(label,value)
dates='；'.join(f"{'A股' if k=='A' else '港股'}：{v}" for k,v in latest.get('market_dates',{}).items())
st.caption(f"最新完整交易日：{dates}。更新于北京时间 {latest.get('run_time_cn','')}。价格单位：A股人民币，港股港元。")
if problems:
    st.warning(f'{len(problems)}只股票更新失败或行情过期，已从持有/观望表和当日触发中排除。')
st.subheader('当日触发记录')
triggers=latest.get('triggers',[])
if triggers:
    st.dataframe(table(triggers,True),width='stretch',hide_index=True)
else:
    st.info('最新完整交易日没有买入或卖出触发。')
st.caption('买入/卖出仅记录趋势翻转的当天；翻多当天同时归入持有，翻空当天归入观望。这里的状态代表策略方向，不是账户真实持仓。')
st.subheader(f'股票池当前信号 · 持有（{len(holds)}只）')
if holds:
    st.dataframe(table(holds),width='stretch',hide_index=True)
else:
    st.info('暂无持有信号。')
st.subheader(f'股票池当前信号 · 观望（{len(waits)}只）')
if waits:
    st.dataframe(table(waits),width='stretch',hide_index=True)
else:
    st.info('暂无观望信号。')
with st.expander('历史买卖触发记录'):
    history=load_json(DATA_DIR/'history.json')
    rows=history.get('records',[]) if history.get('module')=='super-trend' else []
    if rows:
        st.dataframe(table(rows,True),width='stretch',hide_index=True)
    else:
        st.info('暂无历史触发记录。')
with st.expander('数据状态与计算口径'):
    if problems:
        st.dataframe(pd.DataFrame([{'代码':r['ticker'],'名称':r.get('company_name'),'状态':r.get('health'),'行情日期':r.get('data_date',''),'原因':r.get('error','行情未更新，可能停牌或源数据延迟')} for r in problems]),width='stretch',hide_index=True)
    special=[{'代码':r['ticker'],'名称':r.get('company_name'),'复权口径':r.get('adjustment_note'),'数据源':r.get('data_source'),'有效日线数':r.get('daily_bar_count')} for r in fresh]
    if special:
        st.dataframe(pd.DataFrame(special),width='stretch',hide_index=True)
    st.write('从2016年或最早可用数据计算，使用SMA初始化的Wilder ATR(10)。只用已收盘日线，不以当天未收盘价格触发。新股至少需要10根完整日线；停牌/过期股票不参与当日信号。')
    st.write('信号监控不连接券商、不自动下单。买入/卖出按下一交易日开盘执行的规则解释。后复权备用序列会按最新原始报价做等比例归一化，方向不变。')
