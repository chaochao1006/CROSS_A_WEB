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


def render_short_risk():
    st.title('短线风险监控')
    folder = DATA_DIR / 'short-risk'
    latest = load_json(folder / 'latest.json')
    st.caption('日线反弹过滤与过热评分；风险分至少7分触发提醒，不是自动卖出指令。')
    if latest.get('module') != 'short-risk' or latest.get('schema_version') != 1 or latest.get('data_interval') != '1d':
        st.info('等待首次短线风险数据更新。请运行 GitHub Actions 中的 Supertrend Monitor。')
        return
    records = latest.get('records', [])
    st.caption(f"最新完整交易日：{latest.get('market_dates', {}).get('A', '')} ｜ "
               f"股票池 {len(records)} 只 ｜ 正常 {latest.get('success_count', 0)} 只 ｜ "
               f"更新于北京时间 {latest.get('run_time_cn', '')}")
    labels = {'ticker':'代码', 'company_name':'名称', 'data_date':'行情日期', 'close':'复权收盘价',
              'rebound_state':'反弹状态', 'rebound_score':'反弹分', 'short_risk_score':'风险分',
              'risk_level':'风险等级', 'risk_sources':'主要风险', 'rsi6':'RSI6', 'rsi12':'RSI12',
              'deviation20':'偏离MA20(%)', 'return5':'近5日涨幅(%)', 'volume_ratio':'量比',
              'health':'数据状态', 'error':'原因', 'data_warning':'数据提示'}
    columns = ['ticker', 'company_name', 'data_date', 'close', 'rebound_state', 'rebound_score',
               'short_risk_score', 'risk_level', 'risk_sources']

    def show(rows, cols):
        data = pd.DataFrame(rows).reindex(columns=cols)
        if 'risk_sources' in data:
            data['risk_sources'] = data['risk_sources'].map(lambda value: '；'.join(value) if isinstance(value, list) else value)
        st.dataframe(data.rename(columns=labels), width='stretch', hide_index=True)

    st.subheader('当日触发记录')
    if latest.get('triggers'):
        show(latest['triggers'], columns)
    elif latest.get('success_count', 0):
        st.info('最新完整交易日暂无风险分达到7分的股票。')
    else:
        st.warning('本次没有可确认的日线行情，不能据此判断风险。')
    st.subheader('股票池风险排名')
    fresh = [row for row in records if row.get('health') == '正常']
    if fresh:
        show(fresh, columns)
    st.caption('未形成反弹时风险分为0，不代表股票安全。连续多日达标可逐日记录，同日重复运行不重复追加。')
    with st.expander('指标明细与数据状态'):
        show(records, ['ticker', 'company_name', 'data_date', 'rsi6', 'rsi12', 'deviation20',
                       'return5', 'volume_ratio', 'health', 'error', 'data_warning'])
    with st.expander('历史风险触发'):
        history = load_json(folder / 'history.json')
        if history.get('module') == 'short-risk' and history.get('records'):
            show(history['records'], columns)
        else:
            st.info('暂无历史风险触发。')
    with st.expander('评分规则'):
        st.write('收盘价高于MA5/10/20、MA5高于MA10、RSI12大于50、近5日和10日涨幅为正：每项1分，至少4分才计算风险。')
        st.write('风险加分：偏离MA20超过8%/15%为1/2分；RSI6超过75/85为1/2分；RSI12超过65/75为1/2分；K和D均大于80为1分；J大于100为2分；近5日涨幅超过15%/25%为1/2分；近5日曾量比至少1.8且当天量比下降为1分；收盘跌破MA5为1分；RSI6下降为1分；KDJ高位死叉为2分。同一项目取较高档。')
        st.write('0—3分：反弹正常；4—5分：偏热；6—7分：过热；8分及以上：衰竭风险。触发门槛严格大于6分。行情过期、失败或不足60日不触发。')


st.set_page_config(page_title='股票监控',page_icon='📈',layout='wide')
module = st.sidebar.radio('监控模块', ['Supertrend', 'SMC', 'SMC-选', 'Supertrend-选', '短线风险'])
if module == '短线风险':
    if st.button('刷新数据'):
        st.rerun()
    render_short_risk()
    st.stop()
if module in ('SMC', 'SMC-选'):
    if st.button('刷新数据'):
        st.rerun()
    render_smc('smc' if module == 'SMC' else 'smc-selected', module)
    st.stop()
supertrend_module = 'super-trend-selected' if module == 'Supertrend-选' else 'super-trend'
supertrend_folder = DATA_DIR / supertrend_module if module == 'Supertrend-选' else DATA_DIR
st.title(f'{module} 股票监控')
st.caption('日线 ATR(10) × 3 · 收盘确认信号 · 下一交易日开盘执行')
if st.button('刷新数据',help='重新读取已生成的监控结果；行情由GitHub Actions更新。'):
    st.rerun()
latest=load_json(supertrend_folder/'latest.json')
if latest.get('module')!=supertrend_module or latest.get('schema_version')!=1 or latest.get('data_interval')!='1d':
    st.info(f'等待首次{module}数据更新。请运行GitHub Actions中的Supertrend Monitor。')
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
if module == 'Supertrend-选':
    triggers = sorted(triggers, key=lambda row: {'买入': 0, '卖出': 1}.get(row.get('signal', row.get('event', '')), 2))
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
    history=load_json(supertrend_folder/'history.json')
    rows=history.get('records',[]) if history.get('module')==supertrend_module else []
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
