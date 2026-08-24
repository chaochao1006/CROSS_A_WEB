from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

import a_cross_core as core


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
LATEST_PATH = DATA_DIR / "latest.json"
HISTORY_PATH = DATA_DIR / "history.json"
LOG_PATH = DATA_DIR / "last_run.log"


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return str(value)


def result_to_dict(result: core.StockResult, trigger_count: int = 0) -> Dict[str, Any]:
    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "display_name": core.display_stock(result.ticker, result.company_name),
        "trigger_count": trigger_count,
        "data_date": json_safe(result.data_date),
        "latest_close": json_safe(result.latest_close),
        "latest_change_pct": json_safe(result.latest_change_pct),
        "volume_ratio": json_safe(result.volume_ratio),
        "total_score": json_safe(result.total_score),
        "signal_level": result.signal_level,
        "macd_status": result.macd_status,
        "kdj_status": result.kdj_status,
        "rsi_status": result.rsi_status,
        "near_cross_notes": json_safe(result.near_cross_notes),
        "score_parts": json_safe(result.score_parts),
        "technical_summary": result.technical_summary,
        "trigger_basis": "、".join(result.reason_categories) if result.reason_categories else "技术性突破",
        "confidence": result.confidence,
        "risks": json_safe(result.risks),
        "data_source": result.data_source,
        "data_error": result.data_error,
    }


def load_history() -> List[Dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        payload = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            records = payload.get("records", [])
        else:
            records = payload
        return records if isinstance(records, list) else []
    except Exception:
        return []


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def update_history(data_day: date, triggered: List[core.StockResult]) -> Dict[str, int]:
    records = load_history()
    existing_keys = {(r.get("data_day"), r.get("ticker")) for r in records}
    count_by_ticker: Dict[str, int] = {}
    for record in records:
        ticker = str(record.get("ticker") or "")
        if ticker:
            count_by_ticker[ticker] = count_by_ticker.get(ticker, 0) + 1

    date_text = data_day.isoformat()
    trigger_counts: Dict[str, int] = {}
    for result in triggered:
        key = (date_text, result.ticker)
        if key not in existing_keys:
            next_count = count_by_ticker.get(result.ticker, 0) + 1
            records.append(
                {
                    "data_day": date_text,
                    "ticker": result.ticker,
                    "company_name": result.company_name,
                    "display_name": core.display_stock(result.ticker, result.company_name),
                    "trigger_count": next_count,
                    "total_score": round(float(result.total_score), 1),
                    "signal_level": result.signal_level,
                    "latest_close": json_safe(result.latest_close),
                    "latest_change_pct": json_safe(result.latest_change_pct),
                    "created_at": core.china_now().isoformat(),
                }
            )
            count_by_ticker[result.ticker] = next_count
            existing_keys.add(key)
        trigger_counts[result.ticker] = count_by_ticker.get(result.ticker, 1)

    save_json(
        HISTORY_PATH,
        {
            "updated_at": core.china_now().isoformat(),
            "records": records,
        },
    )
    return trigger_counts


def run_monitor() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )

    now_cn = core.china_now()
    data_day = core.latest_official_trading_day(now_cn)
    technical_results: List[core.StockResult] = []
    success_count = 0

    logging.info("开始扫描 %s 只股票，数据交易日：%s", len(core.TICKERS), data_day)
    for index, ticker in enumerate(core.TICKERS, start=1):
        logging.info("[%s/%s] %s", index, len(core.TICKERS), ticker)
        try:
            result = core.analyze_ticker(ticker, data_day)
            if not result.data_error:
                success_count += 1
            if result.total_score >= core.TRIGGER_SCORE and not result.data_error:
                core.analyze_reason(result)
                logging.info("%s 触发，评分 %.1f", ticker, result.total_score)
            else:
                logging.info("%s 未触发，评分 %.1f", ticker, result.total_score)
            technical_results.append(result)
        except Exception as exc:
            logging.exception("%s 分析失败：%s", ticker, exc)
            technical_results.append(core.StockResult(ticker=ticker, company_name=core.get_company_name(ticker), data_error=str(exc)))
        time.sleep(core.SLEEP_BETWEEN_TICKERS)

    triggered = [r for r in technical_results if not r.data_error and r.total_score >= core.TRIGGER_SCORE]
    triggered.sort(key=lambda item: item.total_score, reverse=True)
    trigger_counts = update_history(data_day, triggered)

    payload = {
        "app": "A-CROSS",
        "run_time_cn": core.china_now().isoformat(),
        "data_day": data_day.isoformat(),
        "trigger_score": core.TRIGGER_SCORE,
        "stock_pool_count": len(core.TICKERS),
        "success_count": success_count,
        "triggered_count": len(triggered),
        "tickers": core.TICKERS,
        "triggered": [result_to_dict(r, trigger_counts.get(r.ticker, 1)) for r in triggered],
        "all_results": [result_to_dict(r) for r in technical_results],
    }
    save_json(LATEST_PATH, payload)
    logging.info("写入网页数据：%s，触发 %s 只。", LATEST_PATH, len(triggered))
    return LATEST_PATH


if __name__ == "__main__":
    output_path = run_monitor()
    print(f"数据生成完成：{output_path}")
