from __future__ import annotations

import json
import logging
import math
import time
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
MAX_HISTORY_RECORDS = 200
BOLL_PERIOD = 20
BOLL_STD_MULTIPLIER = 2
BOLL_LOOKBACK_DAYS = 168


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


def calculate_boll_ranking_item(result: core.StockResult) -> Dict[str, Any] | None:
    df = result.df
    if df is None or df.empty:
        return None

    if "TrendClose" in df.columns:
        price = df["TrendClose"]
    elif "Adjusted Close" in df.columns:
        price = df["Adjusted Close"]
    else:
        price = df["Close"]

    close = pd.to_numeric(price, errors="coerce")
    middle = close.rolling(BOLL_PERIOD, min_periods=BOLL_PERIOD).mean()
    std = close.rolling(BOLL_PERIOD, min_periods=BOLL_PERIOD).std(ddof=0)
    upper = middle + BOLL_STD_MULTIPLIER * std
    lower = middle - BOLL_STD_MULTIPLIER * std
    bandwidth = (upper - lower) / middle.replace(0, math.nan)

    boll_df = pd.DataFrame(
        {
            "close": close,
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "bandwidth": bandwidth,
        }
    ).dropna()
    if len(boll_df) < 60:
        return None

    recent_bandwidth = boll_df["bandwidth"].tail(BOLL_LOOKBACK_DAYS)
    if len(recent_bandwidth) < 60:
        return None

    latest = boll_df.iloc[-1]
    latest_bandwidth = float(recent_bandwidth.iloc[-1])
    percentile = float((recent_bandwidth <= latest_bandwidth).mean())

    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "display_name": core.display_stock(result.ticker, result.company_name),
        "data_date": json_safe(result.data_date),
        "latest_close": json_safe(result.latest_close),
        "boll_middle": json_safe(float(latest["middle"])),
        "boll_upper": json_safe(float(latest["upper"])),
        "boll_lower": json_safe(float(latest["lower"])),
        "boll_bandwidth": json_safe(latest_bandwidth),
        "boll_bandwidth_pct": json_safe(latest_bandwidth * 100),
        "boll_percentile": json_safe(percentile),
        "boll_percentile_pct": json_safe(percentile * 100),
    }


def fetch_market_turnover_snapshot(data_day: date) -> Dict[str, Any]:
    if core.ak is None:
        return {
            "data_day": data_day.isoformat(),
            "status": "error",
            "error": "未安装或无法导入 AKShare",
        }

    try:
        df = core.ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            raise RuntimeError("AKShare 返回空数据")
        if "成交量" not in df.columns or "成交额" not in df.columns:
            raise RuntimeError("AKShare 返回数据缺少成交量或成交额字段")

        code_col = "代码" if "代码" in df.columns else None
        if code_col:
            codes = df[code_col].astype(str).str.zfill(6)
            df = df[codes.str.fullmatch(r"\d{6}", na=False)].copy()

        volume_hands = pd.to_numeric(df["成交量"], errors="coerce").sum()
        amount_yuan = pd.to_numeric(df["成交额"], errors="coerce").sum()
        if not math.isfinite(float(volume_hands)) or not math.isfinite(float(amount_yuan)):
            raise RuntimeError("成交量或成交额汇总结果无效")

        return {
            "data_day": data_day.isoformat(),
            "status": "ok",
            "source": "AKShare stock_zh_a_spot_em",
            "stock_count": int(len(df)),
            "volume_hands": float(volume_hands),
            "volume_yi_hands": float(volume_hands) / 100_000_000,
            "amount_yuan": float(amount_yuan),
            "amount_yi_yuan": float(amount_yuan) / 100_000_000,
            "amount_wan_yi_yuan": float(amount_yuan) / 1_000_000_000_000,
        }
    except Exception as exc:
        return {
            "data_day": data_day.isoformat(),
            "status": "error",
            "error": str(exc),
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
            "records": records[-MAX_HISTORY_RECORDS:],
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
    triggered: List[core.StockResult] = []
    boll_rankings: List[Dict[str, Any]] = []
    success_count = 0

    logging.info("开始扫描 %s 只股票，数据交易日：%s", len(core.TICKERS), data_day)
    market_turnover = fetch_market_turnover_snapshot(data_day)
    if market_turnover.get("status") == "ok":
        logging.info(
            "全A成交量：%.2f 亿手，成交额：%.2f 万亿。",
            market_turnover.get("volume_yi_hands") or 0,
            market_turnover.get("amount_wan_yi_yuan") or 0,
        )
    else:
        logging.warning("全A成交量获取失败：%s", market_turnover.get("error", "未知错误"))

    for index, ticker in enumerate(core.TICKERS, start=1):
        logging.info("[%s/%s] %s", index, len(core.TICKERS), ticker)
        try:
            result = core.analyze_ticker(ticker, data_day)
            if not result.data_error:
                success_count += 1
                boll_item = calculate_boll_ranking_item(result)
                if boll_item:
                    boll_rankings.append(boll_item)
            if result.total_score >= core.TRIGGER_SCORE and not result.data_error:
                core.analyze_reason(result)
                triggered.append(result)
                logging.info("%s 触发，评分 %.1f", ticker, result.total_score)
            else:
                logging.info("%s 未触发，评分 %.1f", ticker, result.total_score)
        except Exception as exc:
            logging.exception("%s 分析失败：%s", ticker, exc)
        time.sleep(core.SLEEP_BETWEEN_TICKERS)

    triggered.sort(key=lambda item: item.total_score, reverse=True)
    boll_rankings.sort(key=lambda item: (float(item.get("boll_percentile") or 1), item.get("ticker", "")))
    trigger_counts = update_history(data_day, triggered)

    payload = {
        "app": "A-CROSS",
        "run_time_cn": core.china_now().isoformat(),
        "data_day": data_day.isoformat(),
        "trigger_score": core.TRIGGER_SCORE,
        "stock_pool_count": len(core.TICKERS),
        "success_count": success_count,
        "triggered_count": len(triggered),
        "triggered": [result_to_dict(r, trigger_counts.get(r.ticker, 1)) for r in triggered],
        "boll_ranking_count": len(boll_rankings),
        "boll_rankings": boll_rankings,
        "market_turnover": market_turnover,
    }
    save_json(LATEST_PATH, payload)
    logging.info("写入网页数据：%s，触发 %s 只。", LATEST_PATH, len(triggered))
    return LATEST_PATH


if __name__ == "__main__":
    output_path = run_monitor()
    print(f"数据生成完成：{output_path}")
