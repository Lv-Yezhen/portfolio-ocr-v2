import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Set

from chart import generate_charts
from extractor import _validate_ocr_result, extract_from_image
from holdings import refresh_holdings_markdown, update_holdings
from portfolio import check_pending_confirmations


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
REVIEW_PREFIX = "REVIEW_"
MAX_STATE_HASHES = 200


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
    hashes = state.get("processed_hashes", [])
    if isinstance(hashes, list) and len(hashes) > MAX_STATE_HASHES:
        state["processed_hashes"] = hashes[-MAX_STATE_HASHES:]
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _scan_top_images(watch_dir: str) -> List[str]:
    files: List[str] = []
    if not os.path.isdir(watch_dir):
        return files

    for item in os.scandir(watch_dir):
        if not item.is_file():
            continue
        if item.name.startswith(REVIEW_PREFIX):
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


def _pending_review_path(data_dir: str) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "pending_review.json")


def _load_pending_review(data_dir: str) -> Dict[str, Any]:
    path = _pending_review_path(data_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_pending_review(data_dir: str, review_data: Dict[str, Any]) -> None:
    path = _pending_review_path(data_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)


def _cleanup_stale_reviews(review_data: Dict[str, Any], watch_dir: str) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for image_hash, item in review_data.items():
        if not isinstance(item, dict):
            continue
        review_name = str(item.get("filename") or "").strip()
        original_name = str(item.get("original_filename") or "").strip()
        review_exists = bool(review_name) and os.path.exists(os.path.join(watch_dir, review_name))
        original_exists = bool(original_name) and os.path.exists(os.path.join(watch_dir, original_name))
        # REVIEW_ 文件不存在但原文件存在，视为“用户确认写入前”的过渡态，保留缓存。
        if review_exists or original_exists:
            cleaned[image_hash] = item
    return cleaned


def process_new_images(config: Dict[str, Any], logger: logging.Logger) -> int:
    watch_dir = _resolve_path(config, "watch_dir")
    archive_dir = _resolve_path(config, "archive_dir")
    state_path = _resolve_path(config, "state_file")
    data_dir = _resolve_path(config, "data_dir")

    os.makedirs(watch_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)

    state = _load_state(state_path)
    seen_hash_list = state.get("processed_hashes", [])
    if not isinstance(seen_hash_list, list):
        seen_hash_list = []
    seen_hashes: Set[str] = set(seen_hash_list)
    loaded_pending = _load_pending_review(data_dir)
    pending_reviews = _cleanup_stale_reviews(loaded_pending, watch_dir=watch_dir)
    pending_changed = pending_reviews != loaded_pending
    if pending_changed:
        _save_pending_review(data_dir, pending_reviews)

    files = _scan_top_images(watch_dir)

    processed_count = 0

    def _mark_processed(image_hash: str) -> None:
        if image_hash in seen_hashes:
            return
        seen_hashes.add(image_hash)
        seen_hash_list.append(image_hash)

    if not files:
        logger.debug("未发现新截图")
    else:
        for image_path in files:
            try:
                image_hash = _sha256(image_path)

                if image_hash in seen_hashes:
                    logger.info("重复截图，跳过识别: %s", image_path)
                    archived = _archive_file(image_path, archive_dir)
                    logger.info("已归档: %s", archived)
                    continue

                pending_item = pending_reviews.get(image_hash)
                if isinstance(pending_item, dict) and isinstance(pending_item.get("ocr_result"), dict):
                    cached = pending_item
                    removed = pending_reviews.pop(image_hash, None)
                    if removed is not None:
                        _save_pending_review(data_dir, pending_reviews)
                        pending_changed = True

                    updated = update_holdings(
                        data=cached["ocr_result"],
                        config=config,
                        logger=logger,
                        source_image=image_path,
                    )
                    if not updated:
                        logger.error("缓存写入失败，保留文件待重试: %s", image_path)
                        pending_reviews[image_hash] = cached
                        _save_pending_review(data_dir, pending_reviews)
                        pending_changed = True
                        continue

                    _mark_processed(image_hash)
                    processed_count += 1
                    archived = _archive_file(image_path, archive_dir)
                    logger.info("待确认结果已写入并归档: %s", archived)
                    continue

                result = extract_from_image(image_path=image_path, config=config, logger=logger)
                if result is None:
                    logger.error("OCR失败，保留文件待重试: %s", image_path)
                    continue

                is_valid, reason = _validate_ocr_result(result, config=config)
                if not is_valid:
                    dirname = os.path.dirname(image_path)
                    original_name = os.path.basename(image_path)
                    review_name = original_name if original_name.startswith(REVIEW_PREFIX) else f"{REVIEW_PREFIX}{original_name}"
                    review_path = os.path.join(dirname, review_name)
                    if review_path != image_path:
                        if os.path.exists(review_path):
                            stem, ext = os.path.splitext(review_name)
                            suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
                            review_name = f"{stem}_{suffix}{ext}"
                            review_path = os.path.join(dirname, review_name)
                        os.rename(image_path, review_path)
                    pending_reviews[image_hash] = {
                        "filename": review_name,
                        "original_filename": original_name,
                        "ocr_result": result,
                        "reason": reason or "数值校验失败",
                        "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _save_pending_review(data_dir, pending_reviews)
                    pending_changed = True
                    logger.warning("识别结果已标记待确认: %s reason=%s", review_name, reason)
                    continue

                updated = update_holdings(data=result, config=config, logger=logger, source_image=image_path)
                if not updated:
                    logger.error("持仓更新失败，保留文件待重试: %s", image_path)
                    continue

                _mark_processed(image_hash)
                processed_count += 1
                archived = _archive_file(image_path, archive_dir)
                logger.info("已归档: %s", archived)
            except Exception:
                logger.exception("处理文件失败: %s", image_path)

    state["processed_hashes"] = seen_hash_list
    _save_state(state_path, state)
    if pending_changed:
        refresh_holdings_markdown(config=config, logger=logger)

    _trim_archive(
        archive_dir=archive_dir,
        max_keep=int(config.get("archive_max", 30)),
        logger=logger,
    )
    timeline_changed = check_pending_confirmations(config=config, logger=logger)
    if processed_count > 0 or pending_changed or timeline_changed:
        generate_charts(config=config, logger=logger)
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
