"""
异常快照工具
当检测到异常情况时，自动保存网页 DOM、截图和状态信息到 data/snapshots/

使用方式：
    from .snapshot import save_anomaly_snapshot
    await save_anomaly_snapshot(page, "pot_mismatch", extra={"ws_pot": 100, "dom_pot": 200})
"""

import asyncio
import json
import os
import time
from typing import Dict, Any, Optional

from playwright.async_api import Page

from src.utils.logger import bot_logger


SNAPSHOT_BASE_DIR = os.path.join(os.getcwd(), "data", "snapshots")


async def save_anomaly_snapshot(
    page: Page,
    reason: str,
    extra: Optional[Dict[str, Any]] = None,
    table_id: Optional[str] = None,
) -> Optional[str]:
    """
    保存异常快照到 data/snapshots/

    Args:
        page: Playwright Page 对象
        reason: 异常原因标识（如 "pot_mismatch", "action_failed" 等）
        extra: 附加信息（会被写入 info.json）
        table_id: 桌号（用于文件名）

    Returns:
        快照目录路径，失败返回 None
    """
    if page is None or page.is_closed():
        return None

    try:
        ts = int(time.time())
        tag = reason.replace(" ", "_")[:30]
        dir_name = f"snap_{ts}_{tag}"
        snap_dir = os.path.join(SNAPSHOT_BASE_DIR, dir_name)
        os.makedirs(snap_dir, exist_ok=True)

        # 1. 保存截图
        try:
            screenshot_path = os.path.join(snap_dir, "screenshot.png")
            await page.screenshot(path=screenshot_path, timeout=5000)
        except Exception as e:
            bot_logger.debug(f"快照截图失败: {e}")

        # 2. 保存 HTML
        try:
            html_path = os.path.join(snap_dir, "page.html")
            html_content = await page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            bot_logger.debug(f"快照 HTML 保存失败: {e}")

        # 3. 保存元信息
        info = {
            "timestamp": ts,
            "reason": reason,
            "table_id": table_id,
            "url": page.url,
            "title": await page.title() if not page.is_closed() else "",
        }
        if extra:
            info["extra"] = extra

        info_path = os.path.join(snap_dir, "info.json")
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2, default=str)

        bot_logger.info(f"异常快照已保存: {snap_dir} (原因: {reason})")
        return snap_dir

    except Exception as e:
        bot_logger.debug(f"保存异常快照失败: {e}")
        return None
