import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests


_NAV_CACHE: Dict[Tuple[str, str], Optional[float]] = {}


def _normalize_code(code: str) -> str:
    return str(code or "").strip()


def _normalize_date(date_str: str) -> str:
    return str(date_str or "").strip()


def get_nav(code: str, date: str, logger: Optional[logging.Logger] = None) -> Optional[float]:
    fund_code = _normalize_code(code)
    target_date = _normalize_date(date)
    if not fund_code or not target_date:
        return None

    cache_key = (fund_code, target_date)
    if cache_key in _NAV_CACHE:
        return _NAV_CACHE[cache_key]

    url = "https://api.fund.eastmoney.com/f10/lsjz"
    params = {
        "fundCode": fund_code,
        "pageIndex": 1,
        "pageSize": 1,
        "startDate": target_date,
        "endDate": target_date,
    }
    headers = {
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{fund_code}.html",
        "User-Agent": "Mozilla/5.0",
    }

    nav_value: Optional[float] = None
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=3)
        if resp.status_code != 200:
            if logger:
                logger.warning("净值请求失败: code=%s date=%s status=%s", fund_code, target_date, resp.status_code)
            _NAV_CACHE[cache_key] = None
            return None

        payload = resp.json()
        data = payload.get("Data") if isinstance(payload, dict) else None
        rows = data.get("LSJZList") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            _NAV_CACHE[cache_key] = None
            return None

        row = rows[0] if isinstance(rows[0], dict) else {}
        row_date = str(row.get("FSRQ") or "").strip()
        row_nav = row.get("DWJZ")
        if row_date != target_date:
            _NAV_CACHE[cache_key] = None
            return None

        nav_value = float(str(row_nav).strip())
    except Exception:
        if logger:
            logger.exception("净值查询异常: code=%s date=%s", fund_code, target_date)
        nav_value = None

    _NAV_CACHE[cache_key] = nav_value
    return nav_value


def can_query_today(confirm_hour: int) -> bool:
    now = datetime.now()
    return now.hour >= int(confirm_hour)
