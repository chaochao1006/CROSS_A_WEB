from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
HISTORY_PATH = DATA_DIR / "history.json"


st.set_page_config(page_title="A-CROSS A股金叉监控", page_icon="A", layout="wide")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fmt_pct(value: Any) -> str:
    try:
        if value is None:
            return "N/A"
        return f"{float(value):.2f}%"
    except Exception:
        return "N/A"


def fmt_num(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "N/A"
        return f"{float(value):.{digits}f}"
    except Exception:
        return "N/A"


latest: Dict[str, Any] = load_json(LATEST_PATH, {})
history_payload: Dict[str, Any] = load_json(HISTORY_PATH, {"records": []})
history_records: List[Dict[str, Any]] = history_payload.get("records", [])

st.title("A-CROSS A股金叉监控")

if not latest:
    st.info("还没有监控数据。GitHub Actions 首次运行后，这里会自动显示最新结果。")
    st.stop()

triggered = latest.get("triggered", [])
all_results = latest.get("all_results", [])

metric_cols = st.columns(5)
metric_cols[0].metric("数据交易日", latest.get("data_day", "N/A"))
metric_cols[1].metric("股票池", latest.get("stock_pool_count", 0))
metric_cols[2].metric("成功取数", latest.get("success_count", 0))
metric_cols[3].metric("触发数量", latest.get("triggered_count", 0))
metric_cols[4].metric("触发阈值", latest.get("trigger_score", 60))

st.caption(f"最近运行时间（北京时间）：{latest.get('run_time_cn', 'N/A')}")

st.divider()

st.subheader("触发股票")
if triggered:
    trigger_df = pd.DataFrame(
        [
            {
                "代码": item.get("ticker"),
                "中文名": item.get("company_name"),
                "第几次触发": item.get("trigger_count"),
                "评分": item.get("total_score"),
                "信号等级": item.get("signal_level"),
                "最新价": item.get("latest_close"),
                "涨跌幅": fmt_pct(item.get("latest_change_pct")),
                "成交量倍数": item.get("volume_ratio"),
                "触发依据": item.get("trigger_basis"),
            }
            for item in triggered
        ]
    )
    st.dataframe(trigger_df, use_container_width=True, hide_index=True)

    for item in triggered:
        title = f"{item.get('display_name', item.get('ticker'))}｜{fmt_num(item.get('total_score'), 1)}分｜第{item.get('trigger_count', 1)}次触发"
        with st.expander(title):
            st.write(item.get("technical_summary") or "暂无技术摘要。")
            cols = st.columns(3)
            cols[0].metric("MACD", item.get("macd_status", "N/A"))
            cols[1].metric("KDJ", item.get("kdj_status", "N/A"))
            cols[2].metric("RSI", item.get("rsi_status", "N/A"))
            score_parts = item.get("score_parts") or {}
            if score_parts:
                st.bar_chart(pd.Series(score_parts, name="score"))
            risks = item.get("risks") or []
            if risks:
                st.write("风险提示：")
                for risk in risks:
                    st.write(f"- {risk}")
else:
    st.success("本交易日没有股票达到触发阈值。")

st.subheader("全部评分")
if all_results:
    all_df = pd.DataFrame(
        [
            {
                "代码": item.get("ticker"),
                "中文名": item.get("company_name"),
                "评分": item.get("total_score"),
                "信号等级": item.get("signal_level"),
                "最新价": item.get("latest_close"),
                "涨跌幅": fmt_pct(item.get("latest_change_pct")),
                "成交量倍数": item.get("volume_ratio"),
                "数据状态": item.get("data_error") or "正常",
            }
            for item in all_results
        ]
    )
    st.dataframe(all_df.sort_values("评分", ascending=False), use_container_width=True, hide_index=True)

st.subheader("历史触发")
if history_records:
    history_df = pd.DataFrame(history_records)
    columns = ["data_day", "ticker", "company_name", "trigger_count", "total_score", "signal_level", "latest_close", "latest_change_pct"]
    existing_columns = [col for col in columns if col in history_df.columns]
    st.dataframe(history_df[existing_columns].sort_values(["data_day", "total_score"], ascending=[False, False]), use_container_width=True, hide_index=True)
else:
    st.info("暂无历史触发记录。")

with st.sidebar:
    st.header("股票池")
    tickers = latest.get("tickers", [])
    st.write(f"共 {len(tickers)} 只")
    st.code("\n".join(tickers), language="text")
