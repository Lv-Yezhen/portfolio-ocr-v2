import csv
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from portfolio import record_snapshot


CSV_HEADERS = [
    "代码",
    "名称",
    "总金额",
    "持有金额",
    "待确认金额",
    "持仓成本价",
    "持有份额",
    "昨日收益",
    "持有收益",
    "持有收益率",
    "日涨幅",
    "最新净值",
    "净值日期",
    "更新时间",
    "待确认交易",
]


def get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_path(config: Dict[str, Any], key: str) -> str:
    value = str(config[key])
    return value if os.path.isabs(value) else os.path.join(get_project_root(), value)


def _to_float(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_amount(value: Any, digits: int = 2, use_comma: bool = True) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:,.{digits}f}" if use_comma else f"{number:.{digits}f}"


def _fmt_text(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text if text else "-"


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _load_existing_csv(path: str) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(path):
        return rows

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("代码") or "").strip()
            if code:
                rows[code] = row
    return rows


def _write_csv(path: str, rows: Dict[str, Dict[str, str]]) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for code in sorted(rows.keys()):
            row = rows[code]
            payload = {key: row.get(key, "") for key in CSV_HEADERS}
            writer.writerow(payload)


def _render_markdown(rows: Dict[str, Dict[str, str]]) -> str:
    lines: List[str] = ["# 当前持仓", ""]

    def sort_key(row: Dict[str, str]) -> str:
        return row.get("更新时间", "")

    sorted_rows = sorted(rows.values(), key=sort_key, reverse=True)

    for row in sorted_rows:
        name = row.get("名称", "-")
        code = row.get("代码", "-")
        updated = row.get("更新时间", "-")
        lines.append(f"## {name} ({code})")
        lines.append(f"> 更新时间: {updated}")
        lines.append("")
        lines.append("| 项目 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 总金额(元) | {row.get('总金额', '-')} |")
        lines.append(f"| 持有金额 | {row.get('持有金额', '-')} |")
        lines.append(f"| 待确认金额 | {row.get('待确认金额', '-')} |")
        lines.append(f"| 持仓成本价 | {row.get('持仓成本价', '-')} |")
        lines.append(f"| 持有份额 | {row.get('持有份额', '-')} |")
        lines.append(f"| 今日收益(元) | {row.get('昨日收益', '-')} |")
        lines.append(f"| 持有收益(元) | {row.get('持有收益', '-')} |")
        lines.append(f"| 持有收益率 | {row.get('持有收益率', '-')} |")
        lines.append(f"| 日涨幅 | {row.get('日涨幅', '-')} |")
        lines.append(f"| 最新净值 | {row.get('最新净值', '-')} |")
        lines.append(f"| 净值日期 | {row.get('净值日期', '-')} |")
        lines.append(f"| 待确认交易 | {row.get('待确认交易', '-')} |")
        lines.append("")

    if len(lines) == 2:
        lines.append("暂无持仓数据。")
        lines.append("")

    return "\n".join(lines)


def _write_markdown(path: str, rows: Dict[str, Dict[str, str]]) -> None:
    _ensure_parent(path)
    content = _render_markdown(rows)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _append_history(config: Dict[str, Any], data: Dict[str, Any], source_image: str, updated_at: str) -> None:
    history_path = os.path.join(_resolve_path(config, "log_dir"), "ocr_history.md")
    _ensure_parent(history_path)

    if not os.path.exists(history_path):
        with open(history_path, "w", encoding="utf-8") as f:
            f.write("# OCR识别历史\n\n")

    image_name = os.path.basename(source_image)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    with open(history_path, "a", encoding="utf-8") as f:
        f.write(f"## {updated_at} - {image_name}\n\n")
        f.write("```json\n")
        f.write(payload)
        f.write("\n```\n\n")


def _build_row(data: Dict[str, Any], updated_at: str) -> Dict[str, str]:
    transactions = data.get("transactions")
    tx_text = "[]"
    if isinstance(transactions, list):
        tx_text = json.dumps(transactions, ensure_ascii=False)
    elif transactions is not None:
        tx_text = str(transactions)

    return {
        "代码": _fmt_text(data.get("code")),
        "名称": _fmt_text(data.get("name")),
        "总金额": _fmt_amount(data.get("total_amount"), digits=2),
        "持有金额": _fmt_amount(data.get("hold_amount"), digits=2),
        "待确认金额": _fmt_amount(data.get("pending_amount"), digits=2),
        "持仓成本价": _fmt_amount(data.get("cost_price"), digits=4, use_comma=False),
        "持有份额": _fmt_amount(data.get("shares"), digits=2, use_comma=False),
        "昨日收益": _fmt_amount(data.get("daily_profit"), digits=2),
        "持有收益": _fmt_amount(data.get("hold_profit"), digits=2),
        "持有收益率": _fmt_text(data.get("hold_rate")),
        "日涨幅": _fmt_text(data.get("daily_change")),
        "最新净值": _fmt_amount(data.get("nav"), digits=4, use_comma=False),
        "净值日期": _fmt_text(data.get("nav_date")),
        "更新时间": updated_at,
        "待确认交易": tx_text,
    }


def update_holdings(data: Dict[str, Any], config: Dict[str, Any], logger: logging.Logger, source_image: str) -> bool:
    try:
        code = str(data.get("code") or "").strip()
        if not code:
            logger.error("识别结果缺少基金代码，已跳过更新")
            return False

        csv_path = _resolve_path(config, "holdings_csv")
        md_path = _resolve_path(config, "holdings_md")

        rows = _load_existing_csv(csv_path)
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows[code] = _build_row(data, updated_at)

        _write_csv(csv_path, rows)
        _write_markdown(md_path, rows)
        _append_history(config, data, source_image=source_image, updated_at=updated_at)
        record_snapshot(data=data, config=config, logger=logger, source_image=source_image)

        logger.info("持仓已更新: %s %s", rows[code].get("名称"), code)
        return True
    except Exception:
        logger.exception("update_holdings执行失败")
        return False
