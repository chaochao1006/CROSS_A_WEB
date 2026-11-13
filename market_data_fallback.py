"""Bounded Tencent daily-history fallback, preserving the full indicator history."""
from __future__ import annotations

import time

import pandas as pd
import requests

URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"


def _daily_block(symbol, start, end, adjustment):
    params = {"param": f"{symbol},day,{start},{end},640,{adjustment}"}
    error = None
    for attempt in range(2):
        try:
            response = requests.get(URL, params=params, timeout=20,
                                    headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            payload = response.json()
            if payload.get("code", 0) != 0:
                raise ValueError(f"腾讯日线接口错误: {payload.get('msg', payload.get('code'))}")
            block = payload["data"][symbol]
            rows = block.get(f"{adjustment}day") or block.get("day") or []
            if not rows:
                return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"],
                                    index=pd.DatetimeIndex([]))
            # Tencent order is date, open, close, high, low, volume, ... .
            frame = pd.DataFrame([row[:6] for row in rows],
                                 columns=["date", "Open", "Close", "High", "Low", "Volume"])
            frame.index = pd.to_datetime(frame.pop("date"), errors="raise")
            frame = frame.apply(pd.to_numeric, errors="raise").sort_index()
            if not frame.index.is_unique:
                raise ValueError("腾讯日线日期重复")
            return frame.loc[pd.Timestamp(start):pd.Timestamp(end)]
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            error = exc
            if attempt == 0:
                time.sleep(.5)
    raise ValueError(f"腾讯日线获取失败: {error}") from error


def tencent_a_daily(ticker, expected, start="2016-01-01"):
    if len(ticker) != 6 or not ticker.isdigit() or ticker[0] not in "036":
        raise ValueError("腾讯备用源仅支持沪深A股六位代码")
    symbol = ("sh" if ticker.startswith("6") else "sz") + ticker
    begin, finish = pd.Timestamp(start), pd.Timestamp(expected)
    chunks = []
    # Two calendar years fit below Tencent's 640-bar cap. Do not request the
    # entire range in one call: that silently drops early indicator history.
    for year in range(begin.year, finish.year + 1, 2):
        left = max(begin, pd.Timestamp(f"{year}-01-01"))
        right = min(finish, pd.Timestamp(f"{year + 1}-12-31"))
        frame = _daily_block(symbol, left.date().isoformat(), right.date().isoformat(), "hfq")
        if not frame.empty:
            chunks.append(frame)
    if not chunks:
        raise ValueError("腾讯没有返回可用日线")
    result = pd.concat(chunks).sort_index()
    if not result.index.is_unique:
        raise ValueError("腾讯分段日线重叠")
    last_day = result.index[-1].date().isoformat()
    raw = _daily_block(symbol, last_day, last_day, "")
    if raw.empty or raw.index[-1] != result.index[-1]:
        raise ValueError("腾讯后复权日线缺少可对齐的原始末日价格")
    scale = float(raw.Close.iloc[-1] / result.Close.iloc[-1])
    if not 0 < scale < float("inf"):
        raise ValueError("腾讯复权归一因子无效")
    result.loc[:, ["Open", "High", "Low", "Close"]] *= scale
    # Volume is not used by ST/SMC; retain Tencent's native lot units explicitly.
    return result, "腾讯证券 daily (2-year chunks, verified 1d)", "后复权全历史归一至末日原始价；成交量为腾讯原始单位"
