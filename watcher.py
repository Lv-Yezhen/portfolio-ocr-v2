import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Set

from extractor import extract_from_image
from holdings import update_holdings


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_path(config: Dict[str, Any], key: str) -> str:
    value = str(config[key])
    return value if os.path.isabs(value) else os.path.join(get_project_root(), value)


def _sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_state(state_path: str) -> Dict[str, Any]:
    if not os.path.exists(state_path):
        return {"processed_hashes": []}

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return {"processed_hashes": []}
        if "processed_hashes" not in state or not isinstance(state["processed_hashes"], list):
            state["processed_hashes"] = []
        return state
    except Exception:
        return {"processed_hashes": []}


def _save_state(state_path: str, state: Dict[str, Any]) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _scan_top_images(watch_dir: str) -> List[str]:
    files: List[str] = []
    if not os.path.isdir(watch_dir):
        return files

    for item in os.scandir(watch_dir):
        if not item.is_file():
            continue
        ext = os.path.splitext(item.name)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            files.append(item.path)

    files.sort(key=lambda p: os.path.getmtime(p))
    return files


def _archive_file(image_path: str, archive_dir: str) -> str:
    os.makedirs(archive_dir, exist_ok=True)
    base_name = os.path.basename(image_path)
    target = os.path.join(archive_dir, base_name)

    if os.path.exists(target):
        stem, ext = os.path.splitext(base_name)
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = os.path.join(archive_dir, f"{stem}_{suffix}{ext}")
        idx = 1
        while os.path.exists(target):
            target = os.path.join(archive_dir, f"{stem}_{suffix}_{idx}{ext}")
            idx += 1

    shutil.move(image_path, target)
    return target


def _trim_archive(archive_dir: str, max_keep: int, logger: logging.Logger) -> None:
    if max_keep <= 0 or not os.path.isdir(archive_dir):
        return

    files = []
    for name in os.listdir(archive_dir):
        path = os.path.join(archive_dir, name)
        if os.path.isfile(path):
            files.append(path)

    if len(files) <= max_keep:
        return

    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for old_file in files[max_keep:]:
        try:
            os.remove(old_file)
            logger.info("归档滚动删除: %s", old_file)
        except Exception:
            logger.exception("删除归档文件失败: %s", old_file)


def process_new_images(config: Dict[str, Any], logger: logging.Logger) -> int:
    watch_dir = _resolve_path(config, "watch_dir")
    archive_dir = _resolve_path(config, "archive_dir")
    state_path = _resolve_path(config, "state_file")

    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)

    state = _load_state(state_path)
    seen_hashes: Set[str] = set(state.get("processed_hashes", []))
    files = _scan_top_images(watch_dir)

    if not files:
        logger.debug("未发现新截图")
        return 0

    processed_count = 0

    for image_path in files:
        try:
            image_hash = _sha256(image_path)

            if image_hash in seen_hashes:
                logger.info("重复截图，跳过识别: %s", image_path)
                archived = _archive_file(image_path, archive_dir)
                logger.info("已归档: %s", archived)
                continue

            result = extract_from_image(image_path=image_path, config=config, logger=logger)
            if result is None:
                logger.error("OCR失败，保留文件待重试: %s", image_path)
                continue

            updated = update_holdings(data=result, config=config, logger=logger, source_image=image_path)
            if not updated:
                logger.error("持仓更新失败，保留文件待重试: %s", image_path)
                continue

            seen_hashes.add(image_hash)
            processed_count += 1
            archived = _archive_file(image_path, archive_dir)
            logger.info("已归档: %s", archived)
        except Exception:
            logger.exception("处理文件失败: %s", image_path)

    state["processed_hashes"] = list(seen_hashes)
    _save_state(state_path, state)

    _trim_archive(
        archive_dir=archive_dir,
        max_keep=int(config.get("archive_max", 30)),
        logger=logger,
    )
    return processed_count


def run_watch_loop(config: Dict[str, Any], logger: logging.Logger) -> None:
    interval = int(config.get("scan_interval", 10))
    logger.info("开始监控目录: %s (每%s秒扫描)", config.get("watch_dir"), interval)

    try:
        while True:
            processed = process_new_images(config, logger)
            if processed:
                logger.info("本轮处理完成，共处理新截图: %s", processed)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("监控已停止")
