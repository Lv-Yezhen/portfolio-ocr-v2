# portfolio-ocr-v2

基金 APP 截图 OCR 项目，使用 LM Studio 本地 VLM（OpenAI 兼容接口）识别截图并维护持仓。

## 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置 LM Studio

先复制模板配置：

```bash
cp config.yaml.template config.yaml
```

1. 启动 LM Studio，并加载支持图像输入的本地模型（默认示例：`qwen3-vl-2b-instruct`）。
2. 开启本地 API Server（OpenAI Compatible），默认地址一般是 `http://127.0.0.1:1234`。
3. 在 LM Studio 里配置好系统提示词和 JSON Schema（本项目默认依赖服务端提示词）。
4. 检查 `config.yaml`：

```yaml
api_base: "http://127.0.0.1:1234/v1"
model: "qwen3-vl-2b-instruct"
# 可选：仅服务端要求鉴权时配置
# api_key: "your-key"

# 示例：截图目录可用绝对路径
# watch_dir: "/Users/Lyz/Nutstore Files/openclaw桌面/投资管理/截图"
```

## 3. 配置 `config.yaml`

复制 `config.yaml.template` 为 `config.yaml`，并根据你的实际情况修改 `config.yaml` 中的路径配置。

```bash
cp config.yaml.template config.yaml
```

**注意**：`watch_dir`、`holdings_md`、`holdings_csv`、`state_file` 建议使用**绝对路径**，以避免隐私泄露和路径混淆。例如：

```yaml
watch_dir: "/Users/你的用户名/Nutstore Files/openclaw桌面/投资管理/截图"
holdings_md: "/Users/你的用户名/Nutstore Files/openclaw桌面/投资管理/holdings.md"
holdings_csv: "/Users/你的用户名/Nutstore Files/openclaw桌面/投资管理/holdings.csv"
state_file: "/Users/你的用户名/Nutstore Files/openclaw桌面/投资管理/state.json"
```

## 4. 初始化目录和文件

```bash
python main.py --setup
```

会自动创建：
- `screenshots/` 和 `screenshots/archive/`
- `logs/`
- `holdings.md`、`holdings.csv`、`state.json`
- `logs/ocr_history.md`

## 4. 运行方式

### 持续监控模式

```bash
python main.py --watch
```

程序会按 `config.yaml` 的 `scan_interval` 周期扫描 `screenshots/` 顶层图片，识别后更新持仓并归档。

mac 双击脚本启动/停止（`.command`）：

```bash
./start_watch.command
./stop_watch.command
```

### 单次处理模式

```bash
python main.py --once
```

处理当前目录下待处理截图后退出。

### 单图测试模式

```bash
python main.py --test screenshots/example.jpg
```

直接打印 OCR JSON，便于调试提示词和模型效果。

## 5. 关键行为说明

- 路径支持两种写法：
  - 相对路径：相对项目根目录。
  - 绝对路径：直接写系统完整路径（推荐用于 `holdings_md`、`holdings_csv` 输出到同步盘目录）。
- `start_watch.command` 启动后会在 `holdings.md` 同目录生成 `portfolio_ocr_watch.running` 标记文件；`stop_watch.command` 停止时会删除。
- 目录扫描只看 `screenshots/` 顶层文件，`archive/` 子目录不会重复扫描。
- 使用文件 `sha256` 去重，状态写入 `state.json`。
- 识别结果会：
  - 覆盖更新 `holdings.md`（每个基金仅保留最新一条）
  - 覆盖更新 `holdings.csv`（每个基金仅一行）
  - 追加写入 `logs/ocr_history.md` 历史记录
- 已处理截图会移动到 `screenshots/archive/`，超过 `archive_max` 自动滚动删除旧文件。
- 如果 OCR 或写入失败，截图会保留在 `screenshots/`，便于修复后重试。

## 6. 常见排查

- 调整代码后请重启监控进程，避免旧进程继续运行旧逻辑。
- LM Studio 若返回 `model crashed`，请检查模型常驻配置并重启对应模型服务。
