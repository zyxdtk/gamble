import sqlite3
import os
from typing import Optional, Dict, List

class PlayerDatabase:
    """对手数据持久化存储 (SQLite)"""
    def __init__(self, db_path: str = "data/players.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    user_id TEXT PRIMARY KEY,
                    total_hands INTEGER DEFAULT 0,
                    vpip_count INTEGER DEFAULT 0,
                    pfr_count INTEGER DEFAULT 0,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS player_showdowns (
                    user_id TEXT,
                    hand TEXT,
                    street TEXT,
                    context TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def update_player_stats(self, user_id: str, is_vpip: bool, is_pfr: bool):
        """原子级更新玩家统计数据"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO players (user_id, total_hands, vpip_count, pfr_count, last_seen)
                VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_hands = total_hands + 1,
                    vpip_count = vpip_count + (EXCLUDED.vpip_count),
                    pfr_count = pfr_count + (EXCLUDED.pfr_count),
                    last_seen = CURRENT_TIMESTAMP
            """, (user_id, 1 if is_vpip else 0, 1 if is_pfr else 0))

    def get_player_stats(self, user_id: str) -> Optional[Dict]:
        """查询玩家历史数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT total_hands, vpip_count, pfr_count FROM players WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "hands": row[0],
                    "vpip_count": row[1],
                    "pfr_count": row[2]
                }
        return None

    def record_showdown(self, user_id: str, hand: str, street: str, context: str = ""):
        """记录玩家在摊牌阶段展示的手牌及其背景"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO player_showdowns (user_id, hand, street, context) VALUES (?, ?, ?, ?)",
                (user_id, hand, street, context)
            )

    def get_recent_showdowns(self, user_id: str, limit: int = 10) -> List[Dict]:
        """获取玩家最近的摊牌记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT hand, street, context FROM player_showdowns WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            rows = cursor.fetchall()
            return [{"hand": r[0], "street": r[1], "context": r[2]} for r in rows]
