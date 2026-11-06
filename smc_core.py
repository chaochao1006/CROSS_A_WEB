"""Daily bullish Swing events from the existing LuxAlgo SMC Python port.

Derived from LuxAlgo Smart Money Concepts, CC BY-NC-SA 4.0.
https://www.luxalgo.com/library/indicator/smart-money-concepts-smc/
"""
import numpy as np

SWING_LENGTH = 50


def swing_events(frame, length=SWING_LENGTH):
    """Yield bullish events on the confirmation bar and track bearish breaks for bias."""
    high, low, close = (frame[col].to_numpy(dtype=float) for col in ("High", "Low", "Close"))
    leg = bias = 0
    upper = lower = np.nan
    upper_crossed = lower_crossed = False
    for i in range(length, len(frame)):
        previous_upper, previous_lower = upper, lower
        previous_leg = leg
        origin = i - length
        if high[origin] > high[origin + 1:i + 1].max():
            leg = 0
        elif low[origin] < low[origin + 1:i + 1].min():
            leg = 1
        if leg != previous_leg:
            if leg == 1:
                lower, lower_crossed = low[origin], False
            else:
                upper, upper_crossed = high[origin], False

        if not upper_crossed and close[i] > upper and close[i - 1] <= previous_upper:
            yield i, "Swing CHoCH" if bias == -1 else "Swing BOS", float(upper)
            upper_crossed = True
            bias = 1
        if not lower_crossed and close[i] < lower and close[i - 1] >= previous_lower:
            lower_crossed = True
            bias = -1


def analyze_smc(frame, ticker, name, market, expected):
    data_date = frame.index[-1].date().isoformat()
    health = '正常'
    if data_date != expected:
        health = '行情过期/停牌'
    elif len(frame) <= SWING_LENGTH:
        health = '日线不足'
    record = {'ticker': ticker, 'company_name': name, 'market': market,
              'data_date': data_date, 'health': health}
    events = [
        {**record, 'data_date': frame.index[i].date().isoformat(), 'signal': signal,
         'close': float(frame.Close.iloc[i]), 'level': level}
        for i, signal, level in swing_events(frame)
    ] if health == '正常' else []
    if events:
        record.update(last_event=events[-1]['signal'], last_event_date=events[-1]['data_date'])
    return record, events


