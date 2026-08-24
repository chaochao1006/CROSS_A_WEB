# A-CROSS A股网页监控

这个目录是 A-CROSS 的 Streamlit 网页版。

## 本地运行

```powershell
cd C:\Users\81975\Desktop\每日报告\A\CROSS_A_WEB
pip install -r requirements.txt
python run_monitor.py
streamlit run streamlit_app.py
```

## GitHub Actions 定时

`.github/workflows/a-cross-monitor.yml` 已设置：

```yaml
cron: "0 22 * * 0-4"
```

GitHub Actions 的 cron 使用 UTC 时间，所以它对应北京时间周一到周五早上 6:00。

## Streamlit Community Cloud 部署

1. 把本目录内容推到一个 GitHub 仓库。
2. 打开 Streamlit Community Cloud。
3. New app，选择该仓库。
4. Main file path 填：

```text
streamlit_app.py
```

5. 部署后，网页会读取 GitHub Actions 提交到 `data/latest.json` 和 `data/history.json` 的结果。

## 文件说明

- `a_cross_core.py`：A-CROSS 核心计算逻辑。
- `run_monitor.py`：定时任务入口，抓取 A 股数据并生成 JSON。
- `streamlit_app.py`：网页展示入口。
- `data/latest.json`：最近一次运行结果。
- `data/history.json`：历史触发记录，用来显示第几次触发。
- `.github/workflows/a-cross-monitor.yml`：GitHub Actions 定时任务。
