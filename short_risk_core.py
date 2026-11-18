"""Same daily rebound/overheating scoring rules as the US short-risk monitor."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import datetime as dt
import math
import numpy as np
import pandas as pd

TRIGGER_SCORE = 6  # A trigger requires strictly more than six points.

@dataclass
class ShortRiskResult:
    """保存单只股票的短线反弹状态、过热风险和报告文字。"""

    ticker: str
    date: Optional[dt.date] = None
    close: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    rsi6: Optional[float] = None
    rsi12: Optional[float] = None
    k: Optional[float] = None
    d: Optional[float] = None
    j: Optional[float] = None
    deviation20: Optional[float] = None
    return5: Optional[float] = None
    return10: Optional[float] = None
    volume_ratio: Optional[float] = None
    rebound_score: int = 0
    rebound_state: str = "无法判断"
    short_risk_score: int = 0
    risk_level: str = "无法判断"
    risk_sources: List[str] = field(default_factory=list)
    rebound_reasons: List[str] = field(default_factory=list)
    indicator_summary: str = ""
    observation: str = ""
    error: str = ""
    data_warning: str = ""


def safe_float(value) -> Optional[float]:
    """安全转换为浮点数。"""

    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def calculate_rsi(series: pd.Series, period: int) -> pd.Series:
    """使用Wilder平滑方法计算RSI。"""

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def calculate_kdj(df: pd.DataFrame) -> pd.DataFrame:
    """计算KDJ指标，初始K/D设为50。"""

    df = df.copy()
    low9 = df["Low"].rolling(9).min()
    high9 = df["High"].rolling(9).max()
    rsv = (df["Close"] - low9) / (high9 - low9).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)
    k_values = []
    d_values = []
    k_prev = 50.0
    d_prev = 50.0
    for value in rsv:
        k_today = k_prev * 2 / 3 + float(value) / 3
        d_today = d_prev * 2 / 3 + k_today / 3
        k_values.append(k_today)
        d_values.append(d_today)
        k_prev = k_today
        d_prev = d_today
    df["K"] = k_values
    df["D"] = d_values
    df["J"] = 3 * df["K"] - 2 * df["D"]
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算短线反弹风险所需的均线、RSI、KDJ、成交量和涨幅。"""

    df = df.copy()
    for window in [5, 10, 20, 50]:
        df[f"MA{window}"] = df["Close"].rolling(window).mean()
    df["Deviation20"] = (df["Close"] - df["MA20"]) / df["MA20"] * 100
    df["RSI6"] = calculate_rsi(df["Close"], 6)
    df["RSI12"] = calculate_rsi(df["Close"], 12)
    df = calculate_kdj(df)
    df["Volume_MA20"] = df["Volume"].rolling(20).mean()
    df["Volume_Ratio"] = df["Volume"] / df["Volume_MA20"]
    df["Return_5D"] = df["Close"].pct_change(5) * 100
    df["Return_10D"] = df["Close"].pct_change(10) * 100
    return df


def is_short_rebound(df: pd.DataFrame) -> Tuple[int, str, List[str]]:
    """判断是否处于短线反弹状态，满足4项及以上才进入过热评分。"""

    latest = df.iloc[-1]
    reasons: List[str] = []
    score = 0

    checks = [
        (pd.notna(latest["MA5"]) and latest["Close"] > latest["MA5"], "收盘价站上MA5"),
        (pd.notna(latest["MA10"]) and latest["Close"] > latest["MA10"], "收盘价站上MA10"),
        (pd.notna(latest["MA20"]) and latest["Close"] > latest["MA20"], "收盘价站上MA20"),
        (pd.notna(latest["MA5"]) and pd.notna(latest["MA10"]) and latest["MA5"] > latest["MA10"], "MA5高于MA10"),
        (pd.notna(latest["RSI12"]) and latest["RSI12"] > 50, "RSI12站上50"),
        (pd.notna(latest["Return_5D"]) and latest["Return_5D"] > 0, "近5日收益为正"),
        (pd.notna(latest["Return_10D"]) and latest["Return_10D"] > 0, "近10日收益为正"),
    ]
    for passed, reason in checks:
        if passed:
            score += 1
            reasons.append(reason)

    if score >= 5:
        state = "短线反弹确认"
    elif score >= 4:
        state = "短线反弹初步成立"
    else:
        state = "未形成短线反弹"
    return score, state, reasons


def score_short_rebound_risk(df: pd.DataFrame, result: ShortRiskResult) -> int:
    """在短线反弹状态下，判断是否过热或衰竭。"""

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    risks: List[str] = []

    deviation20 = latest["Deviation20"]
    if pd.notna(deviation20):
        if deviation20 > 15:
            score += 2
            risks.append("偏离MA20超过15%")
        elif deviation20 > 8:
            score += 1
            risks.append("偏离MA20超过8%")

    if latest["RSI6"] > 85:
        score += 2
        risks.append("RSI6大于85")
    elif latest["RSI6"] > 75:
        score += 1
        risks.append("RSI6大于75")

    if latest["RSI12"] > 75:
        score += 2
        risks.append("RSI12大于75")
    elif latest["RSI12"] > 65:
        score += 1
        risks.append("RSI12大于65")

    if latest["K"] > 80 and latest["D"] > 80:
        score += 1
        risks.append("KDJ处于高位")

    if latest["J"] > 100:
        score += 2
        risks.append("J线大于100")

    if pd.notna(latest["Return_5D"]):
        if latest["Return_5D"] > 25:
            score += 2
            risks.append("近5日涨幅超过25%")
        elif latest["Return_5D"] > 15:
            score += 1
            risks.append("近5日涨幅超过15%")

    # 放量冲高后缩量：最近5日曾明显放量，最新成交量低于前一日且仍在高位区域。
    recent_volume_ratio = df["Volume_Ratio"].dropna().tail(5)
    if not recent_volume_ratio.empty and recent_volume_ratio.max() >= 1.8:
        if pd.notna(latest["Volume_Ratio"]) and pd.notna(prev["Volume_Ratio"]) and latest["Volume_Ratio"] < prev["Volume_Ratio"]:
            score += 1
            risks.append("放量冲高后缩量")

    if pd.notna(latest["MA5"]) and latest["Close"] < latest["MA5"]:
        score += 1
        risks.append("跌破MA5")

    if latest["RSI6"] < prev["RSI6"]:
        score += 1
        risks.append("RSI6掉头向下")

    if latest["K"] < latest["D"] and prev["K"] >= prev["D"] and prev["K"] > 80:
        score += 2
        risks.append("KDJ高位死叉")

    result.risk_sources = risks if risks else ["短线反弹正常，暂无明显过热衰竭信号"]
    return score


def risk_level_from_score(score: int) -> str:
    """根据短线风险分数给出风险等级。"""

    if score >= 8:
        return "高位反弹衰竭风险"
    if score >= 6:
        return "短线过热，容易回踩"
    if score >= 4:
        return "短线偏热"
    return "短线反弹正常"
