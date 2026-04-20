# portfolio-ocr-v2

基金 APP 截图 OCR 项目，使用 LM Studio 本地 VLM（OpenAI 兼容接口）识别截图并维护持仓。

## 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置 LM Studio

1. 启动 LM Studio，并加载支持图像输入的本地模型（默认示例：`glm-ocr`）。
2. 开启本地 API Server（OpenAI Compatible），默认地址一般是 `http://127.0.0.1:1234`。
3. 检查 `config.yaml`：

```yaml
api_base: "http://127.0.0.1:1234/v1"
model: "glm-ocr"
api_key: "lm-studio"
```

## 3. 初始化目录和文件

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

- 所有路径都是相对项目根目录（代码中通过 `os.path.dirname(os.path.abspath(__file__))` 定位根目录）。
- 目录扫描只看 `screenshots/` 顶层文件，`archive/` 子目录不会重复扫描。
- 使用文件 `sha256` 去重，状态写入 `state.json`。
- 识别结果会：
  - 覆盖更新 `holdings.md`（每个基金仅保留最新一条）
  - 覆盖更新 `holdings.csv`（每个基金仅一行）
  - 追加写入 `logs/ocr_history.md` 历史记录
- 已处理截图会移动到 `screenshots/archive/`，超过 `archive_max` 自动滚动删除旧文件。
