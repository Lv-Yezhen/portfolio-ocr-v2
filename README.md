# portfolio-ocr-v2

基金 App 截图 OCR 自动化工具。项目使用 LM Studio 或其他 OpenAI 兼容 VLM 接口识别基金截图，并维护本地持仓、交易时间线、操作流水和趋势图。

## 功能概览

- 监听截图目录，自动识别新图片并归档。
- 识别基金持仓/资产详情页，更新 `holdings.md` 和 `holdings.csv`。
- 识别支付宝基金「交易记录」页，记录真实历史买入/卖出交易。
- 维护 `data/transactions.json`，保存基金时间线、待确认交易和历史交易。
- 追加 `data/daily_ops.csv`，作为图表和复盘的数据源。
- 自动确认待确认交易，并在可用时查询历史净值。
- 生成 `charts/chart_{code}.png` 持仓金额和累计收益趋势图。
- 对高风险 OCR 结果做校验，必要时改名为 `REVIEW_...` 等待人工确认。

## 输入截图类型

### 持仓快照

持仓页用于更新当前持仓状态。OCR 输出中的 `screenshot_type` 应为 `holding_snapshot`。

主要字段包括：

- 基金代码、基金名称
- 总金额、持有金额、待确认金额
- 成本价、持有份额
- 今日收益、持有收益、收益率
- 最新净值和净值日期
- 待确认交易列表

### 交易记录

支付宝基金「交易记录」页用于补充真实历史交易。OCR 输出中的 `screenshot_type` 应为 `transaction_history`。

交易记录只写入截图中真实出现的交易，不根据持仓差值推测。每条历史交易会进入 `history_transactions`，并同步追加到 `daily_ops.csv`，来源标记为 `transaction_history`。

## 项目结构

```text
.
├── main.py                         # CLI 入口、初始化和运行模式
├── watcher.py                      # 扫描截图、去重、归档、待确认流程
├── extractor.py                    # 调用 VLM、解析和校验 OCR JSON
├── holdings.py                     # 更新持仓 Markdown/CSV 和 OCR 历史
├── portfolio.py                    # 交易时间线、待确认交易、历史交易记录
├── chart.py                        # 根据 daily_ops.csv 生成趋势图
├── nav_api.py                      # 东方财富历史净值查询
├── paths.py                        # 路径解析、目录创建、JSON 读写工具
├── config.yaml.template            # 配置模板
└── 提取基金数据.preset.json          # LM Studio 结构化输出预设
```

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

复制配置模板：

```bash
cp config.yaml.template config.yaml
```

按需修改 `config.yaml`：

```yaml
api_base: "http://127.0.0.1:1234/v1"
model: "qwen/qwen3-vl-4b"
# api_key: "your-key"

watch_dir: "screenshots"
archive_dir: "screenshots/archive"
log_dir: "logs"

holdings_md: "/path/to/your/holdings.md"
holdings_csv: "/path/to/your/holdings.csv"
state_file: "/path/to/your/state.json"

archive_max: 30
scan_interval: 10

data_dir: "data"
chart_dir: "charts"
nav_confirm_hour: 21
delta_threshold: 10
```

路径可以使用绝对路径，也可以使用相对路径。相对路径会基于项目根目录解析。

## LM Studio 预设

导入或更新仓库中的 `提取基金数据.preset.json`。这份预设同时支持持仓页和交易记录页，并要求模型输出结构化 JSON。

关键要求：

- 必须输出合法 JSON，不输出 Markdown 或解释文本。
- 必须返回 `screenshot_type`。
- 持仓页返回 `holding_snapshot`。
- 交易记录页返回 `transaction_history`。
- 未出现在截图中的字段填 `null` 或空数组。
- 不允许编造、推理或猜测交易。

## 初始化

```bash
python main.py --setup
```

初始化会创建：

- `screenshots/`
- `screenshots/archive/`
- `logs/`
- `data/`
- `charts/`
- `holdings.md`
- `holdings.csv`
- `state.json`
- `logs/ocr_history.md`

## 运行

### 监听模式

```bash
python main.py --watch
```

程序会按 `scan_interval` 扫描 `watch_dir` 顶层图片。处理成功后，图片会移动到 `archive_dir`。

macOS 可使用双击脚本：

```bash
./start_watch.command
./stop_watch.command
```

### 单次处理

```bash
python main.py --once
```

处理当前截图目录中的新图片，然后执行待确认交易检查和图表更新。

### 测试单张图片

```bash
python main.py --test screenshots/example.jpg
```

直接打印 OCR JSON，适合调试模型、接口和 preset。

### 生成图表

```bash
python main.py --chart
```

从 `data/daily_ops.csv` 重新生成 `charts/chart_{code}.png`。

### 清空并重建

```bash
python main.py --reset
```

会清空持仓输出、处理状态、交易追踪数据和图表，用于从零重建。

## 数据文件

### `holdings.md`

面向阅读的当前持仓摘要。每只基金保留最新识别结果。如果有待人工确认的 OCR 结果，会显示在文档顶部。

### `holdings.csv`

当前持仓结构化表格。每只基金保留一行最新状态。

### `logs/ocr_history.md`

保存近期 OCR 原始 JSON，便于回查模型输出。

### `data/transactions.json`

交易追踪主数据文件。按基金代码组织，保存：

- `timeline`：持仓时间线
- `pending_transactions`：待确认交易
- `history_transactions`：交易记录页识别出的真实历史交易
- `is_sold_out`：是否清仓

### `data/daily_ops.csv`

每日操作流水。图表生成依赖这个文件。

## 待确认与人工复核

当 OCR 结果触发高风险校验时，程序会把图片改名为 `REVIEW_原文件名`，并把识别结果缓存到 `data/pending_review.json`。

处理方式：

- 去掉文件名前缀 `REVIEW_`：确认写入。
- 删除该图片：丢弃结果。

## 本地临时目录

`temp/` 已加入 `.gitignore`。这个目录可以用来放样例图、临时测试文件或给 Codex 分析的素材，不会进入版本库。

## 常见问题

### LM Studio 返回错误或模型崩溃

检查 LM Studio 是否开启 OpenAI Compatible API，并确认 `api_base` 和 `model` 与当前加载模型一致。

### OCR 字段错位

先用 `--test` 查看模型原始 JSON。如果字段长期错位，优先调整 `提取基金数据.preset.json`，再考虑代码校验规则。

### 修改代码后监听没有生效

重启监听进程，避免旧进程继续运行旧代码。

### 交易历史没有写入

确认截图是交易记录页，并且 OCR 输出包含：

```json
{
  "screenshot_type": "transaction_history",
  "history_transactions": []
}
```

如果 `history_transactions` 为空，程序会跳过写入并保留图片以便重试。
