"""
Base abstract class for website adapters.
All poker website adapters should implement this interface.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from playwright.async_api import Page


@dataclass
class TableInfo:
    """牌桌信息"""
    url: str
    table_id: Optional[str] = None
    name: Optional[str] = None
    stakes: Optional[str] = None
    players: int = 0
    max_players: int = 9
    avg_pot: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "table_id": self.table_id,
            "name": self.name,
            "stakes": self.stakes,
            "players": self.players,
            "max_players": self.max_players,
            "avg_pot": self.avg_pot,
        }


@dataclass
class TableFilter:
    """牌桌筛选条件"""
    stakes: Optional[str] = None  # e.g., "1/2", "2/5"
    min_players: int = 1
    max_players: int = 9
    min_players_waiting: int = 0  # 等待座位的人数


class WebsiteAdapter(ABC):
    """Abstract base class for poker website adapters."""
    
    def __init__(self):
        # 访问过的桌子记录（避免重复）
        self._visited_table_ids: Set[str] = set()
        self._max_visited_history = 5
    
    @abstractmethod
    def get_name(self) -> str:
        """Return the name of the website."""
        pass
    
    @abstractmethod
    def get_lobby_url(self) -> str:
        """Return the URL of the game lobby."""
        pass
    
    @abstractmethod
    async def is_at_lobby(self, page: Page) -> bool:
        """Check if currently at the lobby page."""
        pass
    
    @abstractmethod
    async def is_at_table(self, page: Page) -> bool:
        """Check if currently at a game table page."""
        pass
    
    @abstractmethod
    async def get_available_tables(
        self, 
        page: Page, 
        filter: Optional[TableFilter] = None
    ) -> List[TableInfo]:
        """Get list of available tables from lobby with optional filtering."""
        pass
    
    @abstractmethod
    async def get_best_available_table(
        self, 
        page: Page, 
        exclude_visited: bool = True,
        filter: Optional[TableFilter] = None
    ) -> Optional[TableInfo]:
        """Get the best available table URL based on criteria.
        
        Args:
            page: The browser page
            exclude_visited: Whether to exclude previously visited tables
            filter: Optional filter criteria
            
        Returns:
            Best table info or None if no suitable table found
        """
        pass
    
    @abstractmethod
    async def open_table(self, page: Page, url: str) -> bool:
        """Open a specific table URL."""
        pass
    
    @abstractmethod
    async def try_sit_down(
        self, 
        page: Page, 
        buyin_amount: Optional[int] = None,
        auto_seat: bool = True
    ) -> bool:
        """Try to sit down at the table.
        
        Args:
            page: The browser page
            buyin_amount: Buy-in amount (optional)
            auto_seat: Try to auto-seat if available
        """
        pass
    
    @abstractmethod
    async def get_game_state(self, page: Page) -> Dict[str, Any]:
        """Extract current game state from the page."""
        pass
    
    @abstractmethod
    async def get_available_actions(self, page: Page) -> Dict[str, Any]:
        """Get available actions and their parameters."""
        pass
    
    @abstractmethod
    async def execute_action(self, page: Page, action: str, amount: Optional[int] = None) -> bool:
        """Execute a game action (fold, call, raise, etc.)."""
        pass
    
    @abstractmethod
    async def sit_out(self, page: Page) -> bool:
        """Sit out from the current hand (check 'Sit Out Next Hand').

        Args:
            page: The browser page

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def add_chips(self, page: Page, amount: Optional[int] = None) -> bool:
        """Add chips while seated at the table.

        Args:
            page: The browser page
            amount: Amount to add (optional, uses default if not specified)
        """
        pass

    @abstractmethod
    async def leave_table(self, page: Page) -> bool:
        """Leave the current table."""
        pass
    
    # === 辅助方法 ===
    
    def mark_table_visited(self, table_id: str) -> None:
        """标记桌子为已访问（避免重复进入）"""
        if table_id:
            self._visited_table_ids.add(table_id)
            # 保持 FIFO 队列
            if len(self._visited_table_ids) > self._max_visited_history:
                # 移除最旧的记录
                oldest = next(iter(self._visited_table_ids))
                self._visited_table_ids.discard(oldest)
    
    def is_table_visited(self, table_id: str) -> bool:
        """检查桌子是否已访问过"""
        return table_id in self._visited_table_ids
    
    def clear_visited_history(self) -> None:
        """清空访问历史"""
        self._visited_table_ids.clear()
    
    def extract_table_id(self, url: str) -> Optional[str]:
        """从 URL 提取桌子 ID（需要子类实现网站特定的逻辑）"""
        import re
        m = re.search(r'/(?:play/)?table/([\d]+)', url)
        return m.group(1) if m else None
