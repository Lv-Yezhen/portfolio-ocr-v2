import base64
import csv
import io
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, cast

import requests
from PIL import Image

from paths import resolve_path


EXPECTED_KEYS = [
    "screenshot_type",
    "code",
    "name",
    "total_amount",
    "hold_amount",
    "pending_amount",
    "cost_price",
    "shares",
    "daily_profit",
    "hold_profit",
    "hold_rate",
    "daily_change",
    "nav",
    "nav_date",
    "transactions",
    "history_transactions",
]

KEY_ALIASES = {
    "screenshot_type": ["screenshot_type", "page_type", "页面类型", "截图类型"],
    "code": ["code", "fund_code", "基金代码", "代码"],
    "name": ["name", "fund_name", "基金名称", "名称"],
    "total_amount": ["total_amount", "total", "总金额", "总资产", "总市值"],
    "hold_amount": ["hold_amount", "holding_amount", "持有金额", "持仓金额"],
    "pending_amount": ["pending_amount", "pending", "待确认金额"],
    "cost_price": ["cost_price", "cost", "持仓成本价", "成本价"],
    "shares": ["shares", "hold_shares", "holding_shares", "持有份额", "份额"],
    "daily_profit": ["daily_profit", "today_profit", "昨日收益", "今日收益", "日收益"],
    "hold_profit": ["hold_profit", "acc_profit", "累计收益", "持有收益"],
    "hold_rate": ["hold_rate", "yield_rate", "收益率", "持有收益率"],
    "daily_change": ["daily_change", "day_change", "日涨幅", "涨跌幅"],
    "nav": ["nav", "latest_nav", "净值", "最新净值"],
    "nav_date": ["nav_date", "净值日期", "估值日期"],
    "transactions": ["transactions", "待确认交易", "pending_transactions"],
    "history_transactions": ["history_transactions", "交易记录", "历史交易", "transaction_history"],
}


def _image_to_data_url(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    mime_by_ext = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
    }
    mime = mime_by_ext.get(ext, "image/jpeg")

    # 尽量保留原始格式与清晰度，避免重编码导致小字识别变差。
    if mime != "image/jpeg":
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    with Image.open(image_path) as img:
        rgb_img = img.convert("RGB")
        buffer = io.BytesIO()
        rgb_img.save(buffer, format="JPEG", quality=95)
        image_bytes = buffer.getvalue()
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _extract_json_segment(text: str) -> Optional[str]:
    if not text:
        return None

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and first < last:
        return text[first : last + 1].strip()

    return None


def _parse_json_content(content: str, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    try:
        snippet = _extract_json_segment(content)
        if not snippet:
            logger.error("VLM响应中未找到JSON对象")
            return None
        parsed = json.loads(snippet)
        if not isinstance(parsed, dict):
            logger.error("VLM返回的JSON不是对象: %s", type(parsed))
            return None
        return parsed
    except Exception:
        logger.exception("解析VLM返回JSON失败")
        return None


def _pick_value(payload: Dict[str, Any], aliases: list) -> Any:
    for key in aliases:
        if key in payload:
            return payload.get(key)
    return None


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    # 有些模型会把真正字段包在 data/result 字段内，先尝试扁平化一层。
    nested = payload.get("data")
    if isinstance(nested, dict):
        source = nested
    else:
        nested = payload.get("result")
        source = nested if isinstance(nested, dict) else payload

    normalized: Dict[str, Any] = {}
    for key in EXPECTED_KEYS:
        value = _pick_value(source, KEY_ALIASES.get(key, [key]))
        normalized[key] = value

    screenshot_type = str(normalized.get("screenshot_type") or "").strip()
    if screenshot_type not in {"holding_snapshot", "transaction_history"}:
        history_transactions = normalized.get("history_transactions")
        if isinstance(history_transactions, list) and history_transactions:
            screenshot_type = "transaction_history"
        else:
            screenshot_type = "holding_snapshot"
    normalized["screenshot_type"] = screenshot_type

    code = normalized.get("code")
    normalized["code"] = str(code).strip() if code is not None else ""

    name = normalized.get("name")
    normalized["name"] = str(name).strip() if name is not None else ""

    tx = normalized.get("transactions")
    if tx is None:
        normalized["transactions"] = []
    elif isinstance(tx, list):
        normalized["transactions"] = tx
    else:
        normalized["transactions"] = [tx]

    history_tx = normalized.get("history_transactions")
    if history_tx is None:
        normalized["history_transactions"] = []
    elif isinstance(history_tx, list):
        normalized["history_transactions"] = history_tx
    else:
        normalized["history_transactions"] = [history_tx]

    return normalized


def _build_payload_variants(model: str, text_prompt: str, data_url: str) -> list:
    # 不同模型/网关对多模态字段兼容性不同，按常见格式依次尝试。
    return [
        {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        },
        {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {"type": "image_url", "image_url": data_url},
                    ],
                }
            ],
        },
        {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": text_prompt,
                }
            ],
            "images": [data_url],
        },
    ]


def _call_lm(
    endpoint: str,
    headers: Dict[str, str],
    model: str,
    text_prompt: str,
    data_url: str,
    logger: logging.Logger,
) -> Optional[Dict[str, Any]]:
    payload_variants = _build_payload_variants(
        model=model,
        text_prompt=text_prompt,
        data_url=data_url,
    )

    response = None
    last_error = ""
    for idx, payload in enumerate(payload_variants):
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=30,
            proxies=cast(Dict[str, str], {"http": None, "https": None}),
        )
        if response.status_code == 200:
            if idx > 0:
                logger.info("LM请求已切换到兼容格式 #%s", idx + 1)
            break
        last_error = response.text[:500]
        if "must be a string" in last_error or "iterating prediction stream" in last_error:
            continue
        continue

    if response is None or response.status_code != 200:
        status = response.status_code if response is not None else "N/A"
        logger.error("调用LM Studio失败: status=%s body=%s", status, last_error)
        return None

    return response.json()


def _is_low_confidence_result(payload: Dict[str, Any]) -> bool:
    if payload.get("screenshot_type") == "transaction_history":
        return False

    important_keys = [
        "hold_amount",
        "pending_amount",
        "cost_price",
        "shares",
        "daily_profit",
        "hold_profit",
        "hold_rate",
        "daily_change",
        "nav",
        "nav_date",
    ]
    filled = sum(1 for key in important_keys if payload.get(key) not in (None, "", "-"))
    # 名称和总金额有了但核心字段几乎全空，通常是OCR错位，触发一次重试。
    return bool(payload.get("name")) and payload.get("total_amount") is not None and filled <= 1


def _has_transaction_amounts(payload: Dict[str, Any]) -> bool:
    tx = payload.get("transactions")
    if not isinstance(tx, list):
        return False
    for item in tx:
        if isinstance(item, dict) and item.get("amount") not in (None, "", "-"):
            return True
    return False


def _should_reject_result(payload: Dict[str, Any]) -> bool:
    # 典型错位：主字段几乎全空，但 transactions 填了金额。
    key_values = [
        payload.get("daily_profit"),
        payload.get("hold_profit"),
        payload.get("hold_rate"),
        payload.get("nav"),
        payload.get("nav_date"),
    ]
    key_empty = all(v in (None, "", "-") for v in key_values)
    return _is_low_confidence_result(payload) and key_empty and _has_transaction_amounts(payload)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _parse_date(text: str) -> datetime:
    raw = str(text or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except Exception:
        return datetime.min


def _load_latest_daily_op(config: Dict[str, Any], code: str) -> Optional[Dict[str, str]]:
    data_dir = resolve_path(config, "data_dir", required=False)
    if not data_dir:
        return None
    daily_ops_path = os.path.join(data_dir, "daily_ops.csv")
    if not os.path.exists(daily_ops_path):
        return None

    latest: Optional[Dict[str, str]] = None
    latest_date = datetime.min
    try:
        with open(daily_ops_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("基金代码") or "").strip() != code:
                    continue
                row_date = _parse_date(str(row.get("日期") or ""))
                if row_date >= latest_date:
                    latest_date = row_date
                    latest = row
    except Exception:
        return None
    return latest


def _validate_ocr_result(payload: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    if payload.get("screenshot_type") == "transaction_history":
        return True, ""

    hold_amount = _to_float(payload.get("hold_amount"))
    shares = _to_float(payload.get("shares"))
    cost_price = _to_float(payload.get("cost_price"))

    if hold_amount is not None and shares is not None and cost_price is not None:
        diff = abs(shares * cost_price - hold_amount) / max(abs(hold_amount), 1.0)
        if diff > 10.0:
            return (
                False,
                "交叉验证失败: shares×cost_price 与 hold_amount 偏差超过10倍",
            )

    code = str(payload.get("code") or "").strip()
    if not code or hold_amount is None:
        return True, ""

    latest = _load_latest_daily_op(config, code=code)
    if not latest:
        return True, ""

    prev_hold = _to_float(latest.get("持有金额"))
    if prev_hold is None or prev_hold <= 0:
        return True, ""

    latest_type = str(latest.get("操作类型") or "").strip()
    ratio = max(hold_amount, prev_hold) / min(hold_amount, prev_hold) if min(hold_amount, prev_hold) > 0 else 0.0
    if ratio > 10.0 and latest_type != "买入":
        return (
            False,
            f"历史环比异常: 与上次持有金额差异{ratio:.2f}倍，且上次操作不是买入",
        )
    return True, ""


def extract_from_image(image_path: str, config: Dict[str, Any], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    try:
        data_url = _image_to_data_url(image_path)
        endpoint = f"{str(config['api_base']).rstrip('/')}/chat/completions"

        headers = {"Content-Type": "application/json"}
        api_key = str(config.get("api_key", "")).strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        model = str(config.get("model", "glm-ocr"))
        text_prompt = (
            "请识别截图类型并返回JSON。"
            "如果是基金持仓/资产详情页，screenshot_type返回holding_snapshot，提取持仓字段。"
            "如果标题或内容为交易记录页，screenshot_type返回transaction_history，"
            "提取基金代码、基金名称，并把每条历史交易写入history_transactions；"
            "history_transactions每项包含type、amount、date、time、status。"
            "不要根据持仓差值推测交易，未在截图中出现的字段填null或空数组。"
        )
        result = _call_lm(
            endpoint=endpoint,
            headers=headers,
            model=model,
            text_prompt=text_prompt,
            data_url=data_url,
            logger=logger,
        )
        if result is None:
            return None
        choices = result.get("choices", [])
        if not choices:
            logger.error("LM Studio返回中缺少choices")
            return None

        message = choices[0].get("message", {})
        content = message.get("content", "")

        # 兼容少量实现把content返回为列表块
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            content = "\n".join(parts)

        if not isinstance(content, str):
            content = str(content)

        parsed = _parse_json_content(content, logger)
        if parsed is None:
            logger.error("VLM原始返回片段: %s", content[:500])
            return None

        if isinstance(parsed, dict) and "error" in parsed and len(parsed.keys()) <= 2:
            logger.error("VLM返回错误对象: %s", parsed.get("error"))
            return None

        normalized = _normalize_payload(parsed)
        if not normalized.get("code"):
            logger.warning("识别结果缺少code，原始JSON键: %s", list(parsed.keys()))
        elif _is_low_confidence_result(normalized):
            logger.warning("识别结果疑似错位，触发一次重试: %s", os.path.basename(image_path))
            retry_prompt = "请重新识别，确保收益/净值字段不要写入transactions。无待确认交易时transactions返回空数组。"
            retry_result = _call_lm(
                endpoint=endpoint,
                headers=headers,
                model=model,
                text_prompt=retry_prompt,
                data_url=data_url,
                logger=logger,
            )
            if retry_result:
                retry_choices = retry_result.get("choices", [])
                if retry_choices:
                    retry_message = retry_choices[0].get("message", {})
                    retry_content = retry_message.get("content", "")
                    if isinstance(retry_content, list):
                        parts = []
                        for item in retry_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                parts.append(str(item.get("text", "")))
                            else:
                                parts.append(str(item))
                        retry_content = "\n".join(parts)
                    if not isinstance(retry_content, str):
                        retry_content = str(retry_content)
                    retry_parsed = _parse_json_content(retry_content, logger)
                    if isinstance(retry_parsed, dict) and "error" not in retry_parsed:
                        retry_normalized = _normalize_payload(retry_parsed)
                        if not _is_low_confidence_result(retry_normalized):
                            normalized = retry_normalized

        if _should_reject_result(normalized):
            logger.error(
                "识别结果疑似字段错位，已拒绝写入（请调整模型/preset）: %s",
                os.path.basename(image_path),
            )
            return None
        return normalized
    except Exception:
        logger.exception("extract_from_image执行异常: image=%s", image_path)
        return None
