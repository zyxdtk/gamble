"""
双工通信核心 — 基于 asyncio.Queue 的点对点消息通道。

用于 Ring Game 中 Platform 和 Player 之间的指令级通信。
与 EventBus 的关系：EventBus 负责全局广播（日志、统计），
AsyncChannel 负责 Platform 和特定 Player 之间的请求-响应通信。
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from src.utils.logger import bot_logger


class MessageType(Enum):
    """消息类型枚举"""

    # Platform -> Player
    TABLE_STATE = "table_state"            # 桌位状态推送
    HAND_STATE = "hand_state"              # 手牌状态推送
    REQUEST_ACTION = "request_action"      # 请求手牌决策
    REQUEST_TABLE_ACTION = "request_table_action"  # 请求桌位决策
    HAND_RESULT = "hand_result"            # 手牌结果
    GAME_OVER = "game_over"                # 游戏结束

    # Player -> Platform
    HAND_ACTION = "hand_action"            # 手牌动作回复
    TABLE_ACTION = "table_action"          # 桌位动作回复


@dataclass
class Message:
    """消息数据类"""
    msg_type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    request_id: Optional[str] = None

    @staticmethod
    def make_request_id() -> str:
        return uuid.uuid4().hex[:8]


class AsyncChannel:
    """
    异步双工通信通道。

    Platform 通过 send_to_player / receive_from_player 与 Player 通信。
    Player 通过 send_to_platform / receive_from_platform 与 Platform 通信。
    request_response 封装请求-响应配对模式。
    """

    def __init__(self, player_id: str):
        self.player_id = player_id
        self._platform_to_player: asyncio.Queue = asyncio.Queue()
        self._player_to_platform: asyncio.Queue = asyncio.Queue()
        self._pending_requests: Dict[str, asyncio.Future] = {}

    # --- Platform 侧 ---

    async def send_to_player(self, msg: Message) -> None:
        """Platform 向 Player 发送消息"""
        await self._platform_to_player.put(msg)

    async def receive_from_player(self, timeout: float = 30.0) -> Message:
        """Platform 等待 Player 的回复"""
        return await asyncio.wait_for(self._player_to_platform.get(), timeout=timeout)

    async def request_response(self, request: Message, timeout: float = 30.0) -> Message:
        """
        请求-响应配对：发送请求后等待对应的响应。

        通过 request_id 将请求和响应配对。
        """
        request.request_id = request.request_id or Message.make_request_id()
        rid = request.request_id

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_requests[rid] = future

        await self.send_to_player(request)

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            bot_logger.warning(f"[Channel] 请求 {rid} 超时 ({timeout}s)")
            raise
        finally:
            self._pending_requests.pop(rid, None)

    # --- Player 侧 ---

    async def send_to_platform(self, msg: Message) -> None:
        """Player 向 Platform 发送消息"""
        # 检查是否是某个 pending request 的响应
        if msg.request_id and msg.request_id in self._pending_requests:
            future = self._pending_requests.pop(msg.request_id)
            if not future.done():
                future.set_result(msg)
            return
        await self._player_to_platform.put(msg)

    async def receive_from_platform(self, timeout: float = 300.0) -> Message:
        """Player 等待 Platform 的消息"""
        return await asyncio.wait_for(self._platform_to_player.get(), timeout=timeout)

    # --- 工具 ---

    @property
    def pending_count(self) -> int:
        return len(self._pending_requests)

    def close(self) -> None:
        """关闭通道，取消所有等待中的请求"""
        for rid, future in self._pending_requests.items():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
