"""Update the independent SMC-选 watchlist using the standard daily SMC rules."""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from run_monitor import DATA_DIR, ROOT, save_snapshot
from smc_core import SWING_LENGTH, analyze_smc
from super_trend_core import completed_prices, load_pool, session_context


def build_selected_snapshot(now=None):
    tickers, names = load_pool(ROOT / "smc_selected_pool.json")
    now = pd.Timestamp.now(tz="Asia/Shanghai") if now is None else pd.Timestamp(now)
    expected, _ = session_context("A", now)

    def scan(ticker):
        name = names.get(ticker, ticker)
        try:
            prices, _, _ = completed_prices(ticker, expected)
            return analyze_smc(prices, ticker, name, "A", expected)
        except Exception as exc:
            return {
                "ticker": ticker,
                "company_name": name,
                "market": "A",
                "health": "更新失败",
                "error": str(exc),
            }, []

    records, events = [], []
    with ThreadPoolExecutor(max_workers=6) as executor:
        for record, history in executor.map(scan, tickers):
            records.append(record)
            events.extend(history)
            if len(records) % 50 == 0:
                print(f"SMC-选: {len(records)}/{len(tickers)} 已处理", flush=True)

    return {
        "module": "smc-selected",
        "schema_version": 1,
        "data_interval": "1d",
        "swing_length": SWING_LENGTH,
        "run_time_cn": now.tz_convert("Asia/Shanghai").isoformat(),
        "market_dates": {"A": expected},
        "records": records,
        "triggers": [event for event in events if event["data_date"] == expected],
        "_events": events,
    }


def main():
    snapshot = build_selected_snapshot()
    save_snapshot(DATA_DIR / "smc-selected", snapshot)
    fresh = sum(record["health"] == "正常" for record in snapshot["records"])
    print(f"SMC-选: {fresh}/{len(snapshot['records'])} 行情正常，{len(snapshot['triggers'])} 个触发")
    if not fresh:
        raise RuntimeError("SMC-选全部股票均无新鲜行情，已保存数据状态")


if __name__ == "__main__":
    main()
