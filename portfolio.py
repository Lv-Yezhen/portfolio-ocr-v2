import csv
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from nav_api import get_nav


DAILY_OPS_HEADERS = [
    "日期",
    "基金代码",
    "基金名称",
    "操作类型",
    "买入卖出金额",
    "持有金额",
    "持有份额",
    "当日净值",
    "累计收益",
    "数据来源",
]


def get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_path(config: Dict[str, Any], key: str) -> str:
    value = str(config.get(key, "")).strip()
    if not value:
        raise ValueError(f"缺少配置项: {key}")
    return value if os.path.isabs(value) else os.path.join(get_project_root(), value)


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except Exception:
        return default


def _safe_round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_tx_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        if len(text) == 5 and "-" in text:
            month_day = datetime.strptime(text, "%m-%d")
            now = datetime.now()
            year = now.year
            if (month_day.month, month_day.day) > (now.month, now.day):
                year -= 1
            return f"{year:04d}-{month_day.month:02d}-{month_day.day:02d}"
    except Exception:
        return None
    return None


def _normalize_nav_date(value: Any) -> str:
    parsed = _normalize_tx_date(value)
    return parsed or _now_date()


def _is_sold_out(hold_amount: float, shares: float) -> bool:
    return abs(hold_amount) < 0.01 or abs(shares) < 0.0001


def _transactions_path(config: Dict[str, Any]) -> str:
    data_dir = _resolve_path(config, "data_dir")
    _ensure_dir(data_dir)
    return os.path.join(data_dir, "transactions.json")


def _daily_ops_path(config: Dict[str, Any]) -> str:
    data_dir = _resolve_path(config, "data_dir")
    _ensure_dir(data_dir)
    return os.path.join(data_dir, "daily_ops.csv")


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


def _save_transactions(config: Dict[str, Any], payload: Dict[str, Any]) -> None:
    path = _transactions_path(config)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _ensure_daily_ops_header(config: Dict[str, Any]) -> None:
    path = _daily_ops_path(config)
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_OPS_HEADERS)
        writer.writeheader()


def _append_daily_op(
    config: Dict[str, Any],
    date: str,
    code: str,
    name: str,
    op_type: str,
    delta_amount: float,
    hold_amount: float,
    shares: float,
    nav: float,
    cumulative_profit: float,
    source: str,
) -> None:
    _ensure_daily_ops_header(config)
    row = {
        "日期": date,
        "基金代码": code,
        "基金名称": name,
        "操作类型": op_type,
        "买入卖出金额": f"{_safe_round(delta_amount, 2):.2f}",
        "持有金额": f"{_safe_round(hold_amount, 2):.2f}",
        "持有份额": f"{_safe_round(shares, 2):.2f}",
        "当日净值": f"{_safe_round(nav, 4):.4f}",
        "累计收益": f"{_safe_round(cumulative_profit, 2):.2f}",
        "数据来源": source,
    }
    with open(_daily_ops_path(config), "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_OPS_HEADERS)
        writer.writerow(row)


def _build_timeline_entry(
    date: str,
    op_type: str,
    hold_amount: float,
    shares: float,
    nav: float,
    cumulative_profit: float,
    delta_amount: float,
    source: str,
) -> Dict[str, Any]:
    return {
        "date": date,
        "type": op_type,
        "hold_amount": _safe_round(hold_amount, 2),
        "shares": _safe_round(shares, 2),
        "nav": _safe_round(nav, 4),
        "cumulative_profit": _safe_round(cumulative_profit, 2),
        "delta_amount": _safe_round(delta_amount, 2),
        "source": source,
    }


def _date_gap_days(left: str, right: str) -> int:
    try:
        left_dt = datetime.strptime(left, "%Y-%m-%d")
        right_dt = datetime.strptime(right, "%Y-%m-%d")
        return abs((left_dt - right_dt).days)
    except Exception:
        return 9999


def _find_pending_transaction(
    pending_transactions: List[Dict[str, Any]],
    op_type: str,
    delta_amount: float,
    threshold: float,
    snapshot_date: str,
) -> Optional[Dict[str, Any]]:
    tolerance = max(float(threshold), 10.0)
    target = abs(float(delta_amount))
    matched: Optional[Dict[str, Any]] = None
    best_key: Optional[Tuple[int, str, str]] = None
    for tx in pending_transactions:
        if str(tx.get("status", "pending")) != "pending":
            continue
        tx_type = str(tx.get("type", "")).strip()
        tx_amount = _to_float(tx.get("amount"), default=-1)
        if tx_type != op_type or tx_amount < 0 or abs(tx_amount - target) > tolerance:
            continue
        expected_date = str(tx.get("expected_date") or "")
        date_gap = _date_gap_days(snapshot_date, expected_date)
        sort_key = (date_gap, expected_date, str(tx.get("added_date") or ""))
        if best_key is None or sort_key < best_key:
            matched = tx
            best_key = sort_key
    return matched


def _normalize_pending_transactions(
    source_txs: Any,
    source_image: str,
) -> List[Dict[str, Any]]:
    if not isinstance(source_txs, list):
        return []
    added: List[Dict[str, Any]] = []
    image_name = os.path.basename(source_image or "")
    for tx in source_txs:
        if not isinstance(tx, dict):
            continue
        tx_type = str(tx.get("type", "")).strip()
        amount = _to_float(tx.get("amount"), default=-1)
        expected_date = _normalize_tx_date(tx.get("expected_date"))
        if tx_type not in {"买入", "卖出"} or amount <= 0 or not expected_date:
            continue
        added.append(
            {
                "type": tx_type,
                "amount": _safe_round(amount, 2),
                "expected_date": expected_date,
                "status": "pending",
                "source_image": image_name,
                "added_date": _now_date(),
            }
        )
    return added


def _dedup_pending(existing: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {
        (str(item.get("type")), f"{_to_float(item.get('amount')):.2f}", str(item.get("expected_date")))
        for item in existing
    }
    result = list(existing)
    for item in candidates:
        sig = (str(item.get("type")), f"{_to_float(item.get('amount')):.2f}", str(item.get("expected_date")))
        if sig in seen:
            continue
        seen.add(sig)
        result.append(item)
    return result


def _ensure_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def record_snapshot(data: Dict[str, Any], config: Dict[str, Any], logger: logging.Logger, source_image: str = "") -> bool:
    code = str(data.get("code") or "").strip()
    if not code:
        return False

    all_data = _load_transactions(config)
    fund = all_data.get(code) if isinstance(all_data.get(code), dict) else None
    if fund is None:
        fund = {"name": str(data.get("name") or "").strip(), "is_sold_out": False, "timeline": [], "pending_transactions": []}

    timeline: List[Dict[str, Any]] = _ensure_dict_list(fund.get("timeline"))
    pending_transactions: List[Dict[str, Any]] = _ensure_dict_list(fund.get("pending_transactions"))

    hold_amount = _to_float(data.get("hold_amount"), 0.0)
    shares = _to_float(data.get("shares"), 0.0)
    nav = _to_float(data.get("nav"), 0.0)
    cumulative_profit = _to_float(data.get("hold_profit"), 0.0)
    date = _normalize_nav_date(data.get("nav_date"))

    delta_threshold = float(config.get("delta_threshold", 10))
    op_type = "修正"
    delta_amount = 0.0
    matched_tx: Optional[Dict[str, Any]] = None
    if timeline:
        prev = timeline[-1]
        prev_hold_amount = _to_float(prev.get("hold_amount"), 0.0)
        delta = hold_amount - prev_hold_amount
        if abs(delta) > delta_threshold:
            likely_type = "买入" if delta > 0 else "卖出"
            matched_tx = _find_pending_transaction(
                pending_transactions,
                likely_type,
                abs(delta),
                delta_threshold,
                date,
            )
            if matched_tx is not None:
                op_type = likely_type
                delta_amount = abs(delta)
            else:
                op_type = "修正"

    timeline.append(
        _build_timeline_entry(
            date=date,
            op_type=op_type,
            hold_amount=hold_amount,
            shares=shares,
            nav=nav,
            cumulative_profit=cumulative_profit,
            delta_amount=delta_amount,
            source="ocr",
        )
    )
    _append_daily_op(
        config=config,
        date=date,
        code=code,
        name=str(data.get("name") or fund.get("name") or "").strip(),
        op_type=op_type,
        delta_amount=delta_amount,
        hold_amount=hold_amount,
        shares=shares,
        nav=nav,
        cumulative_profit=cumulative_profit,
        source="ocr",
    )
    if matched_tx is not None:
        matched_tx["status"] = "confirmed"
        matched_tx["confirmed_date"] = _now_date()
        matched_tx["confirm_source"] = "ocr_screenshot"

    extra_pending = _normalize_pending_transactions(data.get("transactions"), source_image=source_image)
    pending_transactions = _dedup_pending(pending_transactions, extra_pending)

    fund["name"] = str(data.get("name") or fund.get("name") or "").strip()
    fund["timeline"] = timeline
    fund["pending_transactions"] = pending_transactions
    has_pending_buy = any(
        str(tx.get("type")) == "买入" and str(tx.get("status")) == "pending"
        for tx in pending_transactions
        if isinstance(tx, dict)
    )
    fund["is_sold_out"] = _is_sold_out(hold_amount, shares) and not has_pending_buy
    if fund["is_sold_out"] and (hold_amount > 0 or shares > 0):
        fund["is_sold_out"] = False
        logger.info("修正 is_sold_out 标记: %s", code)
    all_data[code] = fund
    _save_transactions(config, all_data)
    logger.info("已记录快照: %s %s (%s)", fund["name"], code, op_type)
    return True


def _is_due(expected_date: str, now: datetime, confirm_hour: int) -> bool:
    try:
        target = datetime.strptime(expected_date, "%Y-%m-%d").date()
    except Exception:
        return False
    today = now.date()
    if target < today:
        return True
    if target > today:
        return False
    return now.hour >= confirm_hour


def _apply_confirm(
    last_timeline: Dict[str, Any],
    tx_type: str,
    amount: float,
    nav: float,
) -> Tuple[float, float]:
    hold_amount = _to_float(last_timeline.get("hold_amount"), 0.0)
    shares = _to_float(last_timeline.get("shares"), 0.0)
    confirmed_shares = amount / nav if nav > 0 else 0.0
    if tx_type == "买入":
        return hold_amount + amount, shares + confirmed_shares
    return max(0.0, hold_amount - amount), max(0.0, shares - confirmed_shares)


def check_pending_confirmations(config: Dict[str, Any], logger: logging.Logger) -> bool:
    all_data = _load_transactions(config)
    if not all_data:
        return False

    now = datetime.now()
    confirm_hour = int(config.get("nav_confirm_hour", 21))
    data_changed = False
    need_save = False

    for code, fund in all_data.items():
        if not isinstance(fund, dict):
            continue
        timeline: List[Dict[str, Any]] = _ensure_dict_list(fund.get("timeline"))
        if not timeline:
            continue
        pending_transactions: List[Dict[str, Any]] = _ensure_dict_list(fund.get("pending_transactions"))
        if not pending_transactions:
            continue

        for tx in pending_transactions:
            if str(tx.get("status", "pending")) != "pending":
                continue
            expected_date = str(tx.get("expected_date") or "").strip()
            if not _is_due(expected_date, now, confirm_hour):
                continue

            tx_type = str(tx.get("type") or "").strip()
            amount = _to_float(tx.get("amount"), default=-1)
            if tx_type not in {"买入", "卖出"} or amount <= 0:
                continue

            nav = get_nav(code=code, date=expected_date, logger=logger)
            if nav is None or nav <= 0:
                fail_count = int(tx.get("failed_days", 0)) + 1
                tx["failed_days"] = fail_count
                tx["last_check_date"] = _now_date()
                if fail_count >= 10:
                    tx["status"] = "expired"
                    tx["expired_date"] = _now_date()
                    tx["expire_reason"] = "nav_unavailable_10_days"
                    logger.warning("待确认交易已过期(连续失败>=10天): code=%s type=%s date=%s", code, tx_type, expected_date)
                    need_save = True
                    continue
                if fail_count >= 3:
                    logger.warning("待确认交易连续失败>=3天: code=%s type=%s date=%s", code, tx_type, expected_date)
                need_save = True
                continue

            last_entry = timeline[-1]
            new_hold_amount, new_shares = _apply_confirm(last_entry, tx_type=tx_type, amount=amount, nav=nav)
            cumulative_profit = _to_float(last_entry.get("cumulative_profit"), 0.0)
            entry = _build_timeline_entry(
                date=expected_date,
                op_type=tx_type,
                hold_amount=new_hold_amount,
                shares=new_shares,
                nav=nav,
                cumulative_profit=cumulative_profit,
                delta_amount=amount,
                source="auto_confirm",
            )
            timeline.append(entry)
            _append_daily_op(
                config=config,
                date=expected_date,
                code=code,
                name=str(fund.get("name") or "").strip(),
                op_type=tx_type,
                delta_amount=amount,
                hold_amount=new_hold_amount,
                shares=new_shares,
                nav=nav,
                cumulative_profit=cumulative_profit,
                source="auto_confirm",
            )
            tx["status"] = "confirmed"
            tx["confirmed_date"] = _now_date()
            has_pending_buy = any(
                str(p.get("type")) == "买入" and str(p.get("status")) == "pending"
                for p in pending_transactions
                if isinstance(p, dict)
            )
            fund["is_sold_out"] = _is_sold_out(new_hold_amount, new_shares) and not has_pending_buy
            if fund["is_sold_out"] and (new_hold_amount > 0 or new_shares > 0):
                fund["is_sold_out"] = False
                logger.info("修正 is_sold_out 标记: %s", code)
            data_changed = True
            need_save = True
            logger.info("已自动确认交易: %s %s %s %.2f", code, tx_type, expected_date, amount)

        fund["timeline"] = timeline
        fund["pending_transactions"] = pending_transactions
        all_data[code] = fund

    if need_save:
        _save_transactions(config, all_data)
    return data_changed


def clear_all_portfolio_data(config: Dict[str, Any], logger: logging.Logger) -> None:
    tx_path = _transactions_path(config)
    daily_path = _daily_ops_path(config)
    chart_dir = _resolve_path(config, "chart_dir")
    _ensure_dir(os.path.dirname(tx_path))
    _ensure_dir(chart_dir)

    with open(tx_path, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

    with open(daily_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_OPS_HEADERS)
        writer.writeheader()

    if os.path.isdir(chart_dir):
        for name in os.listdir(chart_dir):
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(chart_dir, name)
            if os.path.isfile(path):
                os.remove(path)

    logger.info("已清空持仓追踪数据，可重新建仓")
