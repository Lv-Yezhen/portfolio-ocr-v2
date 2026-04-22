import argparse
import csv
import json
import logging
import os
from typing import Any, Dict

import yaml

from chart import generate_charts
from extractor import extract_from_image
from portfolio import DAILY_OPS_HEADERS, clear_all_portfolio_data
from watcher import process_new_images, run_watch_loop


def get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def load_config() -> Dict[str, Any]:
    config_path = os.path.join(get_project_root(), "config.yaml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError("config.yaml格式错误，必须是对象")
    data.setdefault("data_dir", "data")
    data.setdefault("chart_dir", "charts")
    data.setdefault("nav_confirm_hour", 21)
    data.setdefault("delta_threshold", 10)
    return data


def _resolve_path(config: Dict[str, Any], key: str) -> str:
    value = str(config[key])
    return value if os.path.isabs(value) else os.path.join(get_project_root(), value)


def init_logger(config: Dict[str, Any]) -> logging.Logger:
    log_dir = _resolve_path(config, "log_dir")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")

    logger = logging.getLogger("portfolio_ocr")
    logger.setLevel(logging.INFO)
    logger.handlers = []

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def setup_project(config: Dict[str, Any], logger: logging.Logger) -> None:
    watch_dir = _resolve_path(config, "watch_dir")
    archive_dir = _resolve_path(config, "archive_dir")
    log_dir = _resolve_path(config, "log_dir")
    md_path = _resolve_path(config, "holdings_md")
    csv_path = _resolve_path(config, "holdings_csv")
    state_path = _resolve_path(config, "state_file")
    history_path = os.path.join(log_dir, "ocr_history.md")
    data_dir = _resolve_path(config, "data_dir")
    chart_dir = _resolve_path(config, "chart_dir")
    transactions_path = os.path.join(data_dir, "transactions.json")
    daily_ops_path = os.path.join(data_dir, "daily_ops.csv")

    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(chart_dir, exist_ok=True)

    if not os.path.exists(md_path):
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# 当前持仓\n\n暂无持仓数据。\n")

    if not os.path.exists(csv_path):
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            f.write("代码,名称,总金额,持有金额,待确认金额,持仓成本价,持有份额,昨日收益,持有收益,持有收益率,日涨幅,最新净值,净值日期,更新时间,待确认交易\n")

    if not os.path.exists(state_path):
        with open(state_path, "w", encoding="utf-8") as f:
            f.write('{"processed_hashes": []}\n')

    if not os.path.exists(history_path):
        with open(history_path, "w", encoding="utf-8") as f:
            f.write("# OCR识别历史\n\n")

    if not os.path.exists(transactions_path):
        with open(transactions_path, "w", encoding="utf-8") as f:
            f.write("{}\n")

    if not os.path.exists(daily_ops_path):
        with open(daily_ops_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=DAILY_OPS_HEADERS)
            writer.writeheader()

    logger.info("初始化完成")


def reset_project_data(config: Dict[str, Any], logger: logging.Logger) -> None:
    md_path = _resolve_path(config, "holdings_md")
    csv_path = _resolve_path(config, "holdings_csv")
    state_path = _resolve_path(config, "state_file")
    history_path = os.path.join(_resolve_path(config, "log_dir"), "ocr_history.md")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 当前持仓\n\n暂无持仓数据。\n")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("代码,名称,总金额,持有金额,待确认金额,持仓成本价,持有份额,昨日收益,持有收益,持有收益率,日涨幅,最新净值,净值日期,更新时间,待确认交易\n")
    with open(state_path, "w", encoding="utf-8") as f:
        f.write('{"processed_hashes": []}\n')
    with open(history_path, "w", encoding="utf-8") as f:
        f.write("# OCR识别历史\n\n")

    clear_all_portfolio_data(config=config, logger=logger)
    logger.info("已清空全部持仓与追踪数据，可重新建仓")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基金APP截图OCR（LM Studio本地VLM）")
    parser.add_argument("--watch", action="store_true", help="持续监控截图目录")
    parser.add_argument("--once", action="store_true", help="处理当前截图后退出")
    parser.add_argument("--test", type=str, help="测试单张图片并输出JSON")
    parser.add_argument("--setup", action="store_true", help="创建所需目录和空文件")
    parser.add_argument("--chart", action="store_true", help="手动生成折线图")
    parser.add_argument("--reset", action="store_true", help="清空全部持仓/追踪/图表数据")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config()
    logger = init_logger(config)

    if args.setup:
        setup_project(config, logger)
        return

    setup_project(config, logger)

    if args.reset:
        reset_project_data(config, logger)
        return

    if args.test:
        image_path = args.test
        if not os.path.isabs(image_path):
            image_path = os.path.join(get_project_root(), image_path)
        if not os.path.exists(image_path):
            logger.error("测试图片不存在: %s", image_path)
            return

        result = extract_from_image(image_path=image_path, config=config, logger=logger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.once:
        count = process_new_images(config, logger)
        logger.info("一次性处理完成，新处理截图数: %s", count)
        return

    if args.chart:
        changed = generate_charts(config=config, logger=logger)
        logger.info("手动图表生成完成: changed=%s", changed)
        return

    if args.watch:
        run_watch_loop(config, logger)
        return

    logger.info("未指定运行模式，请使用 --watch / --once / --test / --chart / --setup / --reset")


if __name__ == "__main__":
    main()
