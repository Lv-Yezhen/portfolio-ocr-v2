import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict, Optional

import requests
from PIL import Image


def get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _load_prompt() -> str:
    prompt_path = os.path.join(get_project_root(), "prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _image_to_data_url(image_path: str) -> str:
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


def extract_from_image(image_path: str, config: Dict[str, Any], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    try:
        data_url = _image_to_data_url(image_path)
        endpoint = f"{str(config['api_base']).rstrip('/')}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.get('api_key', 'lm-studio')}",
        }

        # 提示词已在LM Studio中配置，这里只发图片
        payload = {
            "model": config.get("model", "glm-ocr"),
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请提取这张基金截图的数据，严格以JSON输出。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }

        response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            logger.error("调用LM Studio失败: status=%s body=%s", response.status_code, response.text[:500])
            return None

        result = response.json()
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

        return _parse_json_content(content, logger)
    except Exception:
        logger.exception("extract_from_image执行异常: image=%s", image_path)
        return None
