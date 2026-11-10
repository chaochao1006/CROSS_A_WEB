"""Update both selected-pool monitors from one batch of daily prices."""

from run_monitor import DATA_DIR, ROOT, save_snapshot
from super_trend_core import build_snapshot, load_pool


def build_selected_snapshots(now=None):
    tickers, names = load_pool(ROOT / "smc_selected_pool.json")
    print(f"选股池: 开始扫描 {len(tickers)} 只股票", flush=True)
    supertrend = build_snapshot(tickers, names, now, include_smc=True, max_workers=6)
    smc = supertrend.pop("_smc")
    supertrend["module"] = "super-trend-selected"
    smc["module"] = "smc-selected"
    return supertrend, smc


def main():
    failed = []
    for label, snapshot in zip(("Supertrend-选", "SMC-选"), build_selected_snapshots()):
        save_snapshot(DATA_DIR / snapshot["module"], snapshot)
        fresh = sum(record["health"] == "正常" for record in snapshot["records"])
        print(f"{label}: {fresh}/{len(snapshot['records'])} 行情正常，{len(snapshot['triggers'])} 个触发")
        if not fresh:
            failed.append(label)
    if failed:
        raise RuntimeError(f"{'、'.join(failed)}无新鲜行情，已保存数据状态")


if __name__ == "__main__":
    main()
