import csv
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_path(config: Dict[str, Any], key: str) -> str:
    value = str(config.get(key, "")).strip()
    if not value:
        raise ValueError(f"缺少配置项: {key}")
    return value if os.path.isabs(value) else os.path.join(get_project_root(), value)


def _daily_ops_path(config: Dict[str, Any]) -> str:
    data_dir = _resolve_path(config, "data_dir")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "daily_ops.csv")


def _transactions_path(config: Dict[str, Any]) -> str:
    data_dir = _resolve_path(config, "data_dir")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "transactions.json")


def _load_transactions(config: Dict[str, Any]) -> Dict[str, Any]:
    path = _transactions_path(config)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_daily_ops(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = _daily_ops_path(config)
    if not os.path.exists(path):
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("基金代码"):
                rows.append(row)
    return rows


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace(",", ""))
    except Exception:
        return default


def _date_sort_key(text: str) -> datetime:
    try:
        return datetime.strptime(str(text), "%Y-%m-%d")
    except Exception:
        return datetime.min


def generate_charts(config: Dict[str, Any], logger: logging.Logger) -> bool:
    rows = _load_daily_ops(config)
    chart_dir = _resolve_path(config, "chart_dir")
    os.makedirs(chart_dir, exist_ok=True)
    fund_meta = _load_transactions(config)

    if not rows:
        return False

    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Arial Unicode MS", "Heiti SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        code = str(row.get("基金代码") or "").strip()
        if not code:
            continue
        grouped.setdefault(code, []).append(row)

    changed = False
    active_codes = set()
    for code, items in grouped.items():
        items.sort(key=lambda x: _date_sort_key(str(x.get("日期") or "")))
        meta = fund_meta.get(code) if isinstance(fund_meta.get(code), dict) else {}
        is_sold_out = bool(meta.get("is_sold_out")) if isinstance(meta, dict) else False
        chart_path = os.path.join(chart_dir, f"chart_{code}.png")
        if is_sold_out:
            if os.path.exists(chart_path):
                os.remove(chart_path)
                changed = True
            continue

        active_codes.add(code)
        x_labels = [str(item.get("日期") or "")[-5:] for item in items]
        x = list(range(len(x_labels)))
        hold_amounts = [_to_float(item.get("持有金额"), 0.0) for item in items]
        profits = [_to_float(item.get("累计收益"), 0.0) for item in items]
        types = [str(item.get("操作类型") or "修正") for item in items]

        fig, ax1 = plt.subplots(figsize=(12, 6), dpi=150)
        ax2 = ax1.twinx()

        ax1.plot(x, hold_amounts, color="#1f77b4", linewidth=2, label="持有金额")
        ax1.fill_between(x, hold_amounts, color="#9ec9f5", alpha=0.3)
        ax2.plot(x, profits, color="#d62728", linestyle="--", linewidth=2, label="累计收益")

        for idx, op in enumerate(types):
            if op == "买入":
                ax1.plot([x[idx]], [hold_amounts[idx]], "o", color="green")
            elif op == "卖出":
                ax1.plot([x[idx]], [hold_amounts[idx]], "o", color="red")
            else:
                ax1.plot([x[idx]], [hold_amounts[idx]], "o", color="gray", markersize=3)

        meta_name = str(meta.get("name") or "") if isinstance(meta, dict) else ""
        name = str(items[-1].get("基金名称") or meta_name)
        ax1.set_title(f"{code} {name}".strip())
        ax1.set_xlabel("日期")
        ax1.set_xticks(x)
        ax1.set_xticklabels(x_labels, rotation=0)
        ax1.set_ylabel("持有金额(元)", color="#1f77b4")
        ax2.set_ylabel("累计收益(元)", color="#d62728")
        ax1.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(chart_path)
        plt.close(fig)
        changed = True

    for name in os.listdir(chart_dir):
        if not name.lower().endswith(".png"):
            continue
        if not name.startswith("chart_"):
            continue
        code = name[6:-4]
        if code not in active_codes:
            path = os.path.join(chart_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                changed = True

    logger.info("图表生成完成，基金数: %s", len(active_codes))
    return changed
