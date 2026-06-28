"""
手牌历史记录器

三层设计：
- HandHistoryStore: 持久化到 data/hand_history/（JSONL 完整记录 + SQLite 查询索引）
- HandRecorder: 积累单手牌数据，从 WS 回调 + auto_player 决策点两个来源收集
- 数据类: PlayerAction / PotAward / DecisionContext / HandRecord

所有记录操作 try/except 包裹，记录失败不影响主流程。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ...utils.logger import bot_logger


# ─── 数据类 ───

@dataclass
class PlayerAction:
    """单个玩家动作"""
    user_id: str = ""
    seat_id: Optional[int] = None
    name: str = ""
    action: str = ""          # bet/call/raise/fold/check
    amount: int = 0
    street: str = ""          # preflop/flop/turn/river
    timestamp: str = ""


@dataclass
class PotAward:
    """底池颁奖"""
    winners: List[str] = field(default_factory=list)   # user_id 列表
    winner_names: List[str] = field(default_factory=list)
    chips: int = 0
    timestamp: str = ""


@dataclass
class DecisionContext:
    """我方决策上下文（来自 ActionChoice + ActionPlan 元数据）"""
    street: str = ""
    action: str = ""
    amount: int = 0
    equity: float = 0.0
    pot_odds: float = 0.0
    ev: float = 0.0
    confidence: float = 1.0
    strategy_name: str = ""
    reasoning: str = ""
    timestamp: str = ""


@dataclass
class HandRecord:
    """单手牌完整记录"""
    hand_id: int = 0
    table_id: str = ""
    timestamp: str = ""
    dealer_seat: Optional[int] = None
    big_blind: int = 0
    my_seat: Optional[int] = None
    my_user_id: str = ""
    my_hole_cards: List[str] = field(default_factory=list)
    community_cards_by_street: Dict[str, List[str]] = field(default_factory=dict)
    community_cards_final: List[str] = field(default_factory=list)
    players: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    actions: List[PlayerAction] = field(default_factory=list)
    pot_awards: List[PotAward] = field(default_factory=list)
    my_decisions: List[DecisionContext] = field(default_factory=list)
    my_profit: int = 0
    chips_start: int = 0
    chips_end: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        # community_cards_by_street 的 key 可能是 int（seat）—— 保证 JSON 可序列化
        return d


# ─── HandHistoryStore ───

class HandHistoryStore:
    """手牌历史持久化存储

    - JSONL: 完整记录（每行一个 JSON 对象），按日期轮转 hands_YYYYMMDD.jsonl
    - SQLite: 可查询摘要索引，通过 jsonl_file + jsonl_line 关联到完整记录
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.path.join(os.getcwd(), "data", "hand_history")
        self._base_dir = base_dir
        self._db_path = os.path.join(base_dir, "hand_history.db")
        self._lock = threading.Lock()
        os.makedirs(base_dir, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 表结构"""
        schema = """
        CREATE TABLE IF NOT EXISTS hands (
            hand_id         INTEGER PRIMARY KEY,
            table_id        TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            dealer_seat     INTEGER,
            big_blind       INTEGER,
            my_seat         INTEGER,
            my_user_id      TEXT,
            my_hole_cards   TEXT,
            community_cards TEXT,
            my_action       TEXT,
            my_amount       INTEGER,
            my_equity       REAL,
            my_pot_odds     REAL,
            my_ev           REAL,
            my_confidence   REAL,
            strategy_name   TEXT,
            my_reasoning    TEXT,
            profit          INTEGER,
            num_actions     INTEGER,
            num_players     INTEGER,
            jsonl_file      TEXT,
            jsonl_line      INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_hands_timestamp ON hands(timestamp);
        CREATE INDEX IF NOT EXISTS idx_hands_table ON hands(table_id);
        CREATE INDEX IF NOT EXISTS idx_hands_profit ON hands(profit);
        """
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.executescript(schema)
                conn.commit()
            finally:
                conn.close()

    def _get_jsonl_path(self) -> str:
        """按日期轮转 JSONL 文件名"""
        date_str = datetime.now().strftime("%Y%m%d")
        return os.path.join(self._base_dir, f"hands_{date_str}.jsonl")

    def save(self, record: HandRecord) -> Optional[Tuple[str, int]]:
        """保存一条手牌记录

        写 JSONL 一行 + 写 SQLite 索引，返回 (jsonl_file, jsonl_line) 或 None（失败时）
        """
        try:
            record_dict = record.to_dict()
            line_str = json.dumps(record_dict, ensure_ascii=False, default=str)
            jsonl_path = self._get_jsonl_path()

            with self._lock:
                # 1. 计算当前行号（写入前文件行数 = 新行的 0-based index）
                line_no = 0
                if os.path.exists(jsonl_path):
                    with open(jsonl_path, "r", encoding="utf-8") as rf:
                        line_no = sum(1 for _ in rf)
                # 追加写 JSONL
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line_str + "\n")

                # 2. 写 SQLite 摘要索引
                self._save_to_sqlite(record, jsonl_path, line_no)

            return (jsonl_path, line_no)
        except Exception as e:
            from src.utils.diagnostics import log_exception_with_traceback
            log_exception_with_traceback(
                bot_logger, e,
                f"[hand_recorder] HandHistoryStore.save 异常 hand_id={record.hand_id}",
                level=logging.DEBUG,
                hand_id=record.hand_id, table_id=self._table_id,
            )
            return None

    def _save_to_sqlite(self, record: HandRecord, jsonl_file: str, jsonl_line: int):
        """写 SQLite 摘要行"""
        # 取我方最后一个决策作为摘要字段
        my_decision = record.my_decisions[-1] if record.my_decisions else None
        my_action = my_decision.action if my_decision else ""
        my_amount = my_decision.amount if my_decision else 0
        my_equity = my_decision.equity if my_decision else 0.0
        my_pot_odds = my_decision.pot_odds if my_decision else 0.0
        my_ev = my_decision.ev if my_decision else 0.0
        my_confidence = my_decision.confidence if my_decision else 1.0
        strategy_name = my_decision.strategy_name if my_decision else ""
        my_reasoning = my_decision.reasoning if my_decision else ""

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO hands (
                    hand_id, table_id, timestamp, dealer_seat, big_blind,
                    my_seat, my_user_id, my_hole_cards, community_cards,
                    my_action, my_amount, my_equity, my_pot_odds, my_ev,
                    my_confidence, strategy_name, my_reasoning,
                    profit, num_actions, num_players,
                    jsonl_file, jsonl_line
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.hand_id, record.table_id, record.timestamp,
                    record.dealer_seat, record.big_blind,
                    record.my_seat, record.my_user_id,
                    json.dumps(record.my_hole_cards, ensure_ascii=False),
                    json.dumps(record.community_cards_final, ensure_ascii=False),
                    my_action, my_amount, my_equity, my_pot_odds, my_ev,
                    my_confidence, strategy_name, my_reasoning,
                    record.my_profit, len(record.actions), len(record.players),
                    jsonl_file, jsonl_line,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def query(
        self,
        hand_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """从 SQLite 查询摘要记录"""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                if hand_id is not None:
                    cur = conn.execute(
                        "SELECT * FROM hands WHERE hand_id = ? ORDER BY timestamp DESC",
                        (hand_id,),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM hands ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()


# ─── HandRecorder ───

class HandRecorder:
    """单桌手牌记录器

    生命周期：start_hand → (on_ws_update * / record_decision *) → finalize_hand
    换桌时调用 abort() 丢弃未完成记录。
    """

    def __init__(self, store: HandHistoryStore, table_id: str):
        self._store = store
        self._table_id = table_id
        self._current: Optional[HandRecord] = None
        self._chips_start: int = 0
        # 累积公牌：WSListener 会被 communityCards 全量替换，
        # 所以手牌记录器自己维护一份按 dealCommunityCards 增量追加的真相
        self._accumulated_community: List[str] = []

    # ── 属性 ──

    @property
    def is_recording(self) -> bool:
        return self._current is not None

    @property
    def current_hand_id(self) -> Optional[int]:
        return self._current.hand_id if self._current else None

    # ── 生命周期 ──

    def start_hand(self, hand_id: int, ws_state: Dict[str, Any]):
        """开始记录新一手牌

        若上一手未结束，先 finalize（尽力保存）。
        """
        if self._current is not None:
            # 上一手未正常结束，尝试保存
            try:
                self.finalize_hand(ws_state)
            except Exception as e:
                from src.utils.diagnostics import log_exception_with_traceback
                log_exception_with_traceback(
                    bot_logger, e,
                    f"[hand_recorder] start_hand 时 finalize 上一手异常 hand_id={hand_id}",
                    level=logging.DEBUG,
                    hand_id=hand_id,
                )

        now = datetime.now().isoformat(timespec="seconds")
        record = HandRecord(
            hand_id=int(hand_id or 0),
            table_id=self._table_id,
            timestamp=now,
        )
        # 新一手牌：重置累积公牌
        self._accumulated_community = []

        # 快照玩家初始筹码 + 我的身份
        my_seat = ws_state.get("my_seat_id")
        my_user_id = ws_state.get("my_user_id")
        record.my_seat = my_seat
        record.my_user_id = str(my_user_id) if my_user_id is not None else ""
        record.dealer_seat = ws_state.get("dealer_seat")
        record.big_blind = int(ws_state.get("big_blind", 0) or 0)

        players = ws_state.get("players", {}) or {}
        chips_start = 0
        for seat, pdata in players.items():
            try:
                seat_int = int(seat)
            except (ValueError, TypeError):
                continue
            chips = int(pdata.get("chips", 0) or 0)
            record.players[str(seat_int)] = {
                "seat_id": seat_int,
                "user_id": str(pdata.get("user_id", "") or ""),
                "name": pdata.get("name", "") or "",
                "chips_start": chips,
                "chips_end": chips,
                "status": pdata.get("status", "active"),
            }
            if my_seat is not None and seat_int == int(my_seat):
                chips_start = chips

        self._chips_start = chips_start
        record.chips_start = chips_start
        self._current = record

    def on_ws_update(self, action: Optional[str], update: Dict[str, Any], ws_state: Dict[str, Any]):
        """WS update 回调入口

        按 action 分发到具体处理方法。只做内存追加，无 I/O。
        """
        if self._current is None or not action:
            return

        try:
            if action in ("deal", "dealCards", "dealHoldCards", "dealHoleCards"):
                self._on_deal_hole_cards(update, ws_state)
            elif action == "dealCommunityCards":
                self._on_deal_community_cards(update, ws_state)
            elif action in ("bet", "call", "raise", "fold", "check"):
                self._on_player_action(action, update, ws_state)
            elif action == "awardPot":
                self._on_award_pot(update, ws_state)
            elif action == "blinds":
                self._on_blinds(update, ws_state)
        except Exception as e:
            from src.utils.diagnostics import log_exception_with_traceback
            log_exception_with_traceback(
                bot_logger, e,
                f"[hand_recorder] on_ws_update 异常 (action={action})",
                level=logging.DEBUG,
                action=action,
                hand_id=getattr(self._current, "hand_id", None),
            )

    def _on_deal_hole_cards(self, update: Dict[str, Any], ws_state: Dict[str, Any]):
        """记录我的底牌"""
        if self._current is None:
            return
        # 优先从 ws_state 读取（已被 WSListener 解析过）
        hole = ws_state.get("hole_cards") or []
        if hole and len(hole) >= 2:
            self._current.my_hole_cards = list(hole)
        # 同时更新玩家牌信息
        for p in update.get("players", []):
            seat = p.get("seat") if p.get("seat") is not None else p.get("seatId")
            if seat is None:
                continue
            key = str(int(seat))
            if key in self._current.players:
                self._current.players[key]["cards"] = p.get("cards", [])

    def _on_deal_community_cards(self, update: Dict[str, Any], ws_state: Dict[str, Any]):
        """记录公牌，按牌数判断街道

        重要：WSListener 的 ws_state["community_cards"] 会被 communityCards 字段全量替换，
        所以这里用 update["cards"]（本街道新增的牌）自己累积，存到 _accumulated_community。
        """
        if self._current is None:
            return
        new_cards = update.get("cards") or []
        if not isinstance(new_cards, list) or not new_cards:
            return
        # 增量追加；用 'in' 去重防止 WS 重复发同张牌
        for c in new_cards:
            if c and c not in self._accumulated_community:
                self._accumulated_community.append(c)
        community = self._accumulated_community
        self._current.community_cards_final = list(community)
        n = len(community)
        street = {3: "flop", 4: "turn", 5: "river"}.get(n, "")
        if street:
            # 记录该街道累积到的公牌（flop=3, turn=4, river=5）
            self._current.community_cards_by_street[street] = list(community)

    def _on_player_action(self, action: str, update: Dict[str, Any], ws_state: Dict[str, Any]):
        """记录玩家动作

        重要：ReplayPoker 协议下，raise 事件的 action 字段有时是 'call'，
        必须用 update 中的金额字段（raiseTo / betAmount / callAmount）反推真实动作。
        """
        if self._current is None:
            return
        user_id = str(update.get("userId", "") or "")
        seat_id = update.get("seatId")
        if seat_id is None:
            seat_id = update.get("seat")
        try:
            seat_id = int(seat_id) if seat_id is not None else None
        except (ValueError, TypeError):
            seat_id = None

        # 根据 update 字段重新分类动作
        real_action, amount = self._classify_action(action, update)

        # 玩家名
        name = ""
        if seat_id is not None:
            pdata = self._current.players.get(str(seat_id))
            if pdata:
                name = pdata.get("name", "")

        street = ws_state.get("current_stage") or ""
        if not street:
            # 通过公牌数推断
            n = len(ws_state.get("community_cards") or [])
            street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(n, "preflop")

        now = datetime.now().isoformat(timespec="seconds")
        self._current.actions.append(PlayerAction(
            user_id=user_id,
            seat_id=seat_id,
            name=name,
            action=real_action,
            amount=amount,
            street=street,
            timestamp=now,
        ))

    @staticmethod
    def _classify_action(raw_action: str, update: Dict[str, Any]) -> tuple:
        """根据 update 字段反推真实动作类型 + 提取金额

        ReplayPoker 协议下 WS 帧的 action 字段不可信：
        - 真正的 raise 经常被标成 'call'，但会带 raiseTo 字段
        - 真正的 bet 经常被标成 'call'，但会带 betAmount 字段
        - 真正的 call 带 callAmount 字段

        Returns:
            (action_str, amount_int)
        """
        # 优先级：raise > bet > call > fold
        if update.get("raiseTo") is not None:
            return "raise", int(update["raiseTo"])
        if update.get("betAmount") is not None:
            return "bet", int(update["betAmount"])
        if update.get("callAmount") is not None:
            return "call", int(update["callAmount"])
        if update.get("chips") is not None and raw_action in ("all_in", "allin"):
            return "all_in", int(update["chips"])

        # fallback：用原始 action + amount 字段
        amount = update.get("amount", 0)
        try:
            amount = int(amount) if amount is not None else 0
        except (ValueError, TypeError):
            amount = 0
        return raw_action, amount

    def _on_award_pot(self, update: Dict[str, Any], ws_state: Dict[str, Any]):
        """记录底池颁奖"""
        if self._current is None:
            return
        pots = update.get("pots", []) or []
        now = datetime.now().isoformat(timespec="seconds")
        for p in pots:
            winners = p.get("winners") or p.get("winner") or []
            if isinstance(winners, dict):
                winners = list(winners.values())
            elif not isinstance(winners, list):
                winners = [winners] if winners else []

            winner_ids: List[str] = []
            winner_names: List[str] = []
            for w in winners:
                if isinstance(w, dict):
                    winner_ids.append(str(w.get("userId", "") or ""))
                    winner_names.append(w.get("name", "") or str(w.get("userId", "?")))
                else:
                    winner_ids.append(str(w))
                    winner_names.append(str(w))

            chips = int(p.get("chips", 0) or 0)
            self._current.pot_awards.append(PotAward(
                winners=winner_ids,
                winner_names=winner_names,
                chips=chips,
                timestamp=now,
            ))

            # 更新赢家结束筹码（粗略：起始 + 赢取）
            for wid in winner_ids:
                for pdata in self._current.players.values():
                    if str(pdata.get("user_id", "")) == wid:
                        pdata["chips_end"] = int(pdata.get("chips_end", 0)) + chips
                        break

    def _on_blinds(self, update: Dict[str, Any], ws_state: Dict[str, Any]):
        """更新大盲注"""
        if self._current is None:
            return
        bb = update.get("minimumRaise")
        if bb is not None:
            try:
                self._current.big_blind = int(bb)
            except (ValueError, TypeError):
                pass

    def record_decision(self, choice, street: str = ""):
        """从 ActionChoice 创建 DecisionContext 追加到 my_decisions

        Args:
            choice: ActionChoice（含 equity/pot_odds/ev/confidence/strategy_name）
            street: 当前街道

        街道推断：auto_player 传进来的 street 经常错（一直被标成 preflop），
        这里以累积公牌数为准做兜底修正。

        amount 修复：choice.amount 是策略"想"下注的金额（常为 0，因 strategy 调
        get_action_for_bet 后由 adapter 算 to_call），但实际浏览器执行的是
        一个不同的金额（call 需付 to_call, raise 需 raise-to）。这里在记录时
        优先用 choice.amount；若为 0（call/raise/check），尝试用 to_call 兜底。
        """
        if self._current is None:
            return
        # 街道兜底：基于累积公牌数推断
        inferred_street = self._infer_street()
        if inferred_street and (not street or street == "preflop"):
            street = inferred_street
        now = datetime.now().isoformat(timespec="seconds")
        # 金额修正：策略常传 0，记录时如果能拿到 to_call 优先用 to_call
        action = getattr(choice, "action", "")
        raw_amount = int(getattr(choice, "amount", 0) or 0)
        if raw_amount <= 0 and action in ("call", "raise", "bet"):
            # 尝试从 choice 的 raw 字段或 self._current.to_call 兜底
            to_call_fallback = getattr(self._current, "to_call", 0) or 0
            if to_call_fallback > 0:
                raw_amount = to_call_fallback
        self._current.my_decisions.append(DecisionContext(
            street=street or "",
            action=action,
            amount=raw_amount,
            equity=float(getattr(choice, "equity", 0.0) or 0.0),
            pot_odds=float(getattr(choice, "pot_odds", 0.0) or 0.0),
            ev=float(getattr(choice, "ev", 0.0) or 0.0),
            confidence=float(getattr(choice, "confidence", 1.0) or 1.0),
            strategy_name=getattr(choice, "strategy_name", "") or "",
            reasoning=getattr(choice, "reasoning", "") or "",
            timestamp=now,
        ))

    def _infer_street(self) -> str:
        """基于累积公牌数推断当前街道"""
        n = len(self._accumulated_community)
        return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(n, "")

    def finalize_hand(self, ws_state: Dict[str, Any]):
        """结束当前手牌，计算盈亏并持久化"""
        if self._current is None:
            return

        try:
            # 计算我方结束筹码
            chips_end = self._chips_start
            my_seat = self._current.my_seat
            players = ws_state.get("players", {}) or {}
            if my_seat is not None:
                for seat, pdata in players.items():
                    try:
                        if int(seat) == int(my_seat):
                            chips_end = int(pdata.get("chips", 0) or 0)
                            break
                    except (ValueError, TypeError):
                        continue

            self._current.chips_end = chips_end
            self._current.my_profit = chips_end - self._chips_start

            # 同步所有玩家的结束筹码
            for seat, pdata in players.items():
                try:
                    seat_int = int(seat)
                except (ValueError, TypeError):
                    continue
                key = str(seat_int)
                if key in self._current.players:
                    self._current.players[key]["chips_end"] = int(pdata.get("chips", 0) or 0)

            # 补全公牌最终状态
            community = ws_state.get("community_cards") or []
            if community:
                self._current.community_cards_final = list(community)

            # 持久化
            self._store.save(self._current)
            bot_logger.debug(
                f"[手牌记录] hand_id={self._current.hand_id} "
                f"profit={self._current.my_profit:+d} 已保存"
            )
        except Exception as e:
            from src.utils.diagnostics import log_exception_with_traceback
            hand_id_dbg = getattr(self._current, "hand_id", "?") if self._current else "?"
            log_exception_with_traceback(
                bot_logger, e,
                f"[hand_recorder] finalize_hand 异常 hand_id={hand_id_dbg}",
                level=logging.DEBUG,
                hand_id=hand_id_dbg,
            )
        finally:
            self._current = None
            self._chips_start = 0
            self._accumulated_community = []

    def abort(self):
        """丢弃当前未完成记录（换桌时调用）"""
        if self._current is not None:
            bot_logger.debug(
                f"[手牌记录] hand_id={self._current.hand_id} 已丢弃（换桌）"
            )
        self._current = None
        self._chips_start = 0
        self._accumulated_community = []
