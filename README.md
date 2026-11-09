# Supertrend 股票网页监控

网页包含日线 Supertrend、SMC 和 SMC-选。Supertrend 使用 ATR(10) × 3。

SMC 和 Supertrend 共用 `stock_pool.json` 及同一批已收盘复权日线。SMC 使用 Swing 长度 50，监控绿色 Swing BOS 和 CHoCH，页面显示当日触发、股票池状态和历史触发。SMC 快照与历史分别保存为 `data/smc/latest.json` 和 `data/smc/history.json`。

SMC-选使用相同的 SMC 规则，独立股票池为 `smc_selected_pool.json`，初始包含 2026-11-09 估值筛选表中的 660 只 A 股。GitHub Actions 分步更新，结果保存在 `data/smc-selected/`。本地可单独运行 `python run_smc_selected.py`。

页面依次显示：当日买入/卖出触发、当前持有、当前观望；历史触发和异常取数放在折叠区。
买入/卖出只在收盘趋势翻转当天出现，订单规则为下一可交易日开盘执行。当前持有/观望是策略方向，不是实际账户仓位。

## 股票池

编辑 `stock_pool.json` 的 `tickers` 列表即可调整股票池；`names` 是中文名称映射。
当前监控76只股票（72只A股、4只港股）。代码必须用引号保留前导零，港股格式如 `02476.HK`。

## 本地运行

```powershell
cd "C:\Users\81975\Desktop\每日报告\A\CROSS_A_WEB"
python -m pip install -r requirements.txt
python run_monitor.py
python -m streamlit run streamlit_app.py
```

## 自动更新

GitHub Actions 的 **Supertrend Monitor** 每个工作日北京时间18:17运行，A股和港股均已收盘；支持 `Run workflow` 手动刷新。
推送代码后，手动运行一次该工作流，网页读取新的 `data/latest.json` 和 `data/history.json`。
网页的刷新按钮只重新读取快照，不能替代后台行情更新。

## 部署

保持现有Streamlit Community Cloud仓库及入口 `streamlit_app.py` 即可，无需新建网页。
本地修改需要提交并推送到部署使用的GitHub分支，云端才会更新。

## 数据与规则

- 从2016年或最早可用数据计算；前9根只用于初始化ATR。
- A股按交易日历和北京时间15:15后确认收盘；港股按XHKG日历，计入最多10分钟收市竞价后再等待15分钟，支持半日市。
- 拒绝周/月/季线数据和不合法OHLC；股票数据过期或取数失败时单独显示，不伪装成观望或新触发。
- 默认东方财富前复权，早期含非正价格时改用后复权并归一至最新报价；网页披露该口径。港股另有经过日线周期校验的Yahoo备用源。
- 本模块仅计算信号，不训练模型、不调用LLM、不连接券商，也不自动交易。
- 重复运行按股票、信号日和买卖方向去重；历史最多保存1000条。
- 港股交易时段依据：[港交所证券市场交易时间](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=en)。

## 检查

```powershell
python -m unittest discover -s tests -v
```
