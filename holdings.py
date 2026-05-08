import csv
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List

from paths import ensure_dir, ensure_parent, load_json_object, resolve_path
from portfolio import record_snapshot, record_transaction_history


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
    ensure_parent(path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for code in sorted(rows.keys()):
            row = rows[code]
            payload = {key: row.get(key, "") for key in CSV_HEADERS}
            writer.writerow(payload)


def _md_cell(value: Any) -> str:
    text = str(value or "-").replace("|", "\\|").replace("\n", " ").strip()
    return text if text else "-"


def _pending_review_path(config: Dict[str, Any]) -> str:
    data_dir = resolve_path(config, "data_dir")
    ensure_dir(data_dir)
    return os.path.join(data_dir, "pending_review.json")


def _load_pending_review(config: Dict[str, Any]) -> Dict[str, Any]:
    return load_json_object(_pending_review_path(config))


def _render_markdown(rows: Dict[str, Dict[str, str]], pending_reviews: Dict[str, Any]) -> str:
    lines: List[str] = ["# 当前持仓", ""]
    pending_items = [item for item in pending_reviews.values() if isinstance(item, dict)]
    if pending_items:
        pending_items.sort(key=lambda item: str(item.get("detected_at") or ""), reverse=True)
        lines.append("> ⚠️ **待确认识别结果**")
        lines.append(">")
        for idx, item in enumerate(pending_items):
            if idx > 0:
                lines.append(">")
            lines.append("> ---")
            lines.append(">")
            ocr = item.get("ocr_result") if isinstance(item.get("ocr_result"), dict) else {}
            fund_name = str(ocr.get("name") or "-").strip()
            fund_code = str(ocr.get("code") or "").strip()
            fund = f"{fund_name} {fund_code}".strip() if fund_code else fund_name
            lines.append(f"> **{_md_cell(item.get('filename'))}** - {_md_cell(fund)}")
            lines.append(f"> 拦截原因: {_md_cell(item.get('reason'))}")
            lines.append(">")
            lines.append("> | 字段 | 识别值 |")
            lines.append("> |------|--------|")
            lines.append(f"> | 总金额 | {_md_cell(_fmt_amount(ocr.get('total_amount'), digits=2, use_comma=True))} |")
            lines.append(f"> | 持有金额 | {_md_cell(_fmt_amount(ocr.get('hold_amount'), digits=2, use_comma=True))} |")
            lines.append(f"> | 成本价 | {_md_cell(_fmt_amount(ocr.get('cost_price'), digits=4, use_comma=True))} |")
            lines.append(f"> | 份额 | {_md_cell(_fmt_amount(ocr.get('shares'), digits=2, use_comma=True))} |")
            lines.append(f"> | 持有收益 | {_md_cell(_fmt_amount(ocr.get('hold_profit'), digits=2, use_comma=True))} |")
            lines.append(f"> | 最新净值 | {_md_cell(_fmt_amount(ocr.get('nav'), digits=4, use_comma=True))} |")
        lines.append(">")
        lines.append("> 去掉 `REVIEW_` 前缀 = 确认写入；删除文件 = 丢弃。")
        lines.append("")

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

    if not sorted_rows:
        lines.append("暂无持仓数据。")
        lines.append("")

    return "\n".join(lines)


def _write_markdown(path: str, rows: Dict[str, Dict[str, str]], pending_reviews: Dict[str, Any]) -> None:
    ensure_parent(path)
    content = _render_markdown(rows, pending_reviews=pending_reviews)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _trim_history_entries(history_path: str, max_entries: int = 30) -> None:
    if max_entries <= 0 or not os.path.exists(history_path):
        return
    with open(history_path, "r", encoding="utf-8") as f:
        content = f.read()
    entries = re.findall(r"(?ms)^## .+?(?=^## |\Z)", content)
    if len(entries) <= max_entries:
        return
    trimmed = "# OCR识别历史\n\n" + "".join(entries[-max_entries:])
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(trimmed)


def _append_history(config: Dict[str, Any], data: Dict[str, Any], source_image: str, updated_at: str) -> None:
    history_path = os.path.join(resolve_path(config, "log_dir"), "ocr_history.md")
    ensure_parent(history_path)

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
    _trim_history_entries(history_path, max_entries=30)


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


def _update_transaction_history(data: Dict[str, Any], config: Dict[str, Any], logger: logging.Logger, source_image: str, updated_at: str) -> bool:
    updated = record_transaction_history(data=data, config=config, logger=logger, source_image=source_image)
    if not updated:
        return False

    csv_path = resolve_path(config, "holdings_csv")
    md_path = resolve_path(config, "holdings_md")
    rows = _load_existing_csv(csv_path)
    pending_reviews = _load_pending_review(config)
    _write_markdown(md_path, rows, pending_reviews=pending_reviews)
    _append_history(config, data, source_image=source_image, updated_at=updated_at)
    logger.info("交易历史已更新: %s %s", data.get("name"), data.get("code"))
    return True


def _update_holding_snapshot(data: Dict[str, Any], config: Dict[str, Any], logger: logging.Logger, source_image: str, updated_at: str) -> bool:
    csv_path = resolve_path(config, "holdings_csv")
    md_path = resolve_path(config, "holdings_md")

    rows = _load_existing_csv(csv_path)
    code = str(data.get("code") or "").strip()
    rows[code] = _build_row(data, updated_at)

    pending_reviews = _load_pending_review(config)
    _write_csv(csv_path, rows)
    _write_markdown(md_path, rows, pending_reviews=pending_reviews)
    _append_history(config, data, source_image=source_image, updated_at=updated_at)
    record_snapshot(data=data, config=config, logger=logger, source_image=source_image)

    logger.info("持仓已更新: %s %s", rows[code].get("名称"), code)
    return True


def update_holdings(data: Dict[str, Any], config: Dict[str, Any], logger: logging.Logger, source_image: str) -> bool:
    try:
        code = str(data.get("code") or "").strip()
        if not code:
            logger.error("识别结果缺少基金代码，已跳过更新")
            return False

        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        if data.get("screenshot_type") == "transaction_history":
            return _update_transaction_history(data, config, logger, source_image, updated_at)

        return _update_holding_snapshot(data, config, logger, source_image, updated_at)
    except Exception:
        logger.exception("update_holdings执行失败")
        return False


def refresh_holdings_markdown(config: Dict[str, Any], logger: logging.Logger) -> None:
    try:
        csv_path = resolve_path(config, "holdings_csv")
        md_path = resolve_path(config, "holdings_md")
        rows = _load_existing_csv(csv_path)
        pending_reviews = _load_pending_review(config)
        _write_markdown(md_path, rows, pending_reviews=pending_reviews)
    except Exception:
        logger.exception("刷新 holdings.md 失败")
