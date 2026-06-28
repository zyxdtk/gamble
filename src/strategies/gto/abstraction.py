"""
抽象层：将连续的牌面/动作空间映射到有限的抽象桶

核心思路：
- CardAbstraction: 将169种起手牌 + 无数种公共牌组合映射到有限的 equity bucket
- ActionAbstraction: 将连续的下注尺度离散化为有限个加注档位
- InfoSet: 信息集 = 牌面bucket + 动作历史 的组合键，CFR的最小查表单位
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from treys import Card, Evaluator, Deck


# ── 常量 ──────────────────────────────────────────────

# 169种规范起手牌 (13口袋对 + 78同花 + 78非同花)
RANKS = "23456789TJQKA"
SUIT_MAP = {"s": 0, "h": 1, "d": 2, "c": 3}


# ── 动作抽象 ──────────────────────────────────────────

class ActionAbstraction:
    """
    动作抽象：将连续下注尺度离散化

    默认4个加注档位:
    - MIN:   最小加注 (2BB or 1x prev raise)
    - HALF:  半池 (0.5x pot)
    - POT:   满池 (1x pot)
    - ALLIN: 全下
    """

    # 档位名称 → 相对底池的倍数
    SIZING_PRESETS = {
        "min": 0.0,     # 最小加注，由游戏规则决定
        "half_pot": 0.5,
        "pot": 1.0,
        "allin": float("inf"),
    }

    def __init__(self, sizes: Optional[List[str]] = None):
        """
        Args:
            sizes: 使用的加注档位列表，默认全部
        """
        self.sizes = sizes or ["min", "half_pot", "pot", "allin"]

    def get_abstract_actions(self, pot: int, to_call: int, min_raise: int,
                             stack: int, big_blind: int = 2) -> List[Tuple[str, int]]:
        """
        返回抽象化后的可选行动列表

        Returns:
            [(action_name, amount), ...] 每个行动的名称和具体金额
        """
        actions = []

        # FOLD/CHECK (根据是否有to_call)
        if to_call > 0:
            actions.append(("fold", 0))
        else:
            actions.append(("check", 0))

        # CALL (如果有to_call)
        if to_call > 0:
            call_amount = min(to_call, stack)
            actions.append(("call", call_amount))

        # RAISE 档位
        for size_name in self.sizes:
            if size_name == "min":
                amount = min_raise
            elif size_name == "allin":
                amount = stack
            else:
                multiplier = self.SIZING_PRESETS[size_name]
                amount = int(pot * multiplier) + to_call

            # 修正：不小于最小加注，不超过筹码
            amount = max(amount, min_raise)
            amount = min(amount, stack)

            # 过滤无效/重复
            if amount > to_call and amount <= stack:
                # 检查是否和已有行动重复
                existing_amounts = {a[1] for a in actions}
                if amount not in existing_amounts:
                    actions.append((f"raise_{size_name}", amount))

        return actions

    def action_to_index(self, action_name: str) -> int:
        """将行动名映射到索引"""
        all_names = ["fold", "check", "call"] + [f"raise_{s}" for s in self.sizes]
        return all_names.index(action_name) if action_name in all_names else 0

    def index_to_action(self, idx: int) -> str:
        """将索引映射回行动名"""
        all_names = ["fold", "check", "call"] + [f"raise_{s}" for s in self.sizes]
        return all_names[idx] if idx < len(all_names) else "fold"


# ── 牌面抽象 ──────────────────────────────────────────

class CardAbstraction:
    """
    牌面抽象：将牌面映射到有限的 equity bucket

    分两层：
    1. Preflop: 169种起手牌直接映射（无需抽象）
    2. Postflop: 基于equity百分位映射到N个bucket

    Bucket数越多越精确但状态空间越大，典型取值:
    - Flop: 10-20 buckets
    - Turn: 10-20 buckets
    - River: 10-20 buckets
    """

    def __init__(self, flop_buckets: int = 10, turn_buckets: int = 10,
                 river_buckets: int = 10, num_opponents: int = 1):
        self.flop_buckets = flop_buckets
        self.turn_buckets = turn_buckets
        self.river_buckets = river_buckets
        self.num_opponents = num_opponents
        self._evaluator = Evaluator()
        self._bucket_cache: Dict[str, int] = {}

    def get_preflop_bucket(self, hand_str: str) -> int:
        """
        Preflop bucket: 直接使用169种手牌编码

        Args:
            hand_str: 规范化手牌字符串如 "AKs", "QQ", "72o"

        Returns:
            0-168 的bucket索引
        """
        return self._hand_str_to_index(hand_str)

    def get_postflop_bucket(self, hole_cards: List[int], board_cards: List[int],
                            street: str = "flop") -> int:
        """
        Postflop bucket: 基于equity百分位映射

        蒙特卡洛采样计算equity，然后按百分位映射到bucket

        Args:
            hole_cards: treys格式的手牌
            board_cards: treys格式的公共牌
            street: "flop"/"turn"/"river"

        Returns:
            bucket索引 (0 ~ N-1)
        """
        cache_key = self._make_cache_key(hole_cards, board_cards)
        if cache_key in self._bucket_cache:
            return self._bucket_cache[cache_key]

        equity = self._calculate_equity_mc(hole_cards, board_cards)
        num_buckets = {
            "flop": self.flop_buckets,
            "turn": self.turn_buckets,
            "river": self.river_buckets,
        }.get(street, self.flop_buckets)

        bucket = min(int(equity * num_buckets), num_buckets - 1)
        self._bucket_cache[cache_key] = bucket
        return bucket

    def _calculate_equity_mc(self, hole_cards: List[int], board_cards: List[int],
                             iterations: int = 300) -> float:
        """蒙特卡洛估算equity"""
        if not hole_cards or len(hole_cards) < 2:
            return 0.0

        wins = 0
        ties = 0

        known_cards = set(hole_cards + board_cards)

        for _ in range(iterations):
            # 从剩余牌中随机发牌
            remaining = [c for c in Deck().cards if c not in known_cards]
            import random
            random.shuffle(remaining)

            # 发对手手牌
            villain_hands = []
            idx = 0
            for _ in range(self.num_opponents):
                if idx + 2 <= len(remaining):
                    villain_hands.append([remaining[idx], remaining[idx + 1]])
                    idx += 2

            # 补全公共牌
            cards_needed = 5 - len(board_cards)
            sim_board = list(board_cards)
            if idx + cards_needed <= len(remaining):
                sim_board.extend(remaining[idx:idx + cards_needed])
                idx += cards_needed
            else:
                continue

            if len(sim_board) < 5 or not villain_hands:
                continue

            # 比较牌力
            try:
                hero_score = self._evaluator.evaluate(hole_cards, sim_board)
                villain_scores = [
                    self._evaluator.evaluate(vh, sim_board) for vh in villain_hands
                ]
                best_villain = min(villain_scores)

                if hero_score < best_villain:
                    wins += 1
                elif hero_score == best_villain:
                    ties += 1
            except Exception as e:
                # 之前 silent continue：但 MCP 模式下这种 silent 会让 equity 静默偏低
                # 这里降级为 debug（每 100 次打一次），避免日志爆炸
                from src.utils.diagnostics import log_exception_with_traceback
                _ = log_exception_with_traceback  # 显式 import 防 lint 警告
                abs_logger = logging.getLogger("gto_abstraction")
                if not getattr(self, "_eq_debug_throttled", False):
                    self._eq_debug_throttled = True
                    log_exception_with_traceback(
                        abs_logger, e,
                        "[abstraction] 单次 equity 评估异常，continue "
                        "(后续只打 debug，不重复 traceback)",
                        level=logging.DEBUG,
                        hero=hole_cards, board=sim_board,
                    )
                continue

        return (wins + ties / 2) / iterations if iterations > 0 else 0.0

    def _hand_str_to_index(self, hand_str: str) -> int:
        """169种起手牌 → 0-168索引

        编码规则: AA=0, KK=1, ..., 22=12 (最强→最弱)
        RANKS="23456789TJQKA", 所以rank_order[A]=12, [2]=0
        口袋对: 12-rank_order[r] → AA(12)→0, 22(0)→12
        """
        rank_order = {r: i for i, r in enumerate(RANKS)}

        if len(hand_str) == 2:
            # 口袋对: AA=0, KK=1, ..., 22=12
            r = hand_str[0].upper()
            return 12 - rank_order.get(r, 0)
        elif len(hand_str) == 3:
            r1 = hand_str[0].upper()
            r2 = hand_str[1].upper()
            is_suited = hand_str[2] == "s"

            # hi=大牌的rank_order值, lo=小牌的
            r1_idx = rank_order.get(r1, 0)
            r2_idx = rank_order.get(r2, 0)
            hi = max(r1_idx, r2_idx)
            lo = min(r1_idx, r2_idx)

            # 13口袋对 + 78同花 + 78非同花
            # 同花/非同花: 按hi降序+lo降序排列
            # 转为"强度序": hi越大越强
            if is_suited:
                offset = 13
            else:
                offset = 13 + 78

            if hi == lo:
                return 12 - hi  # 口袋对

            # 非对子: 遍历hi从12到1, lo从hi-1到0
            # 排列序号 = sum_{i=hi+1}^{12}(i) + (hi-lo-1)
            # 简化: 用组合编号
            pair_index = 0
            for h in range(12, hi, -1):
                pair_index += h
            pair_index += (hi - lo - 1)
            return offset + pair_index

        return 168  # 未知

    def _make_cache_key(self, hole_cards: List[int], board_cards: List[int]) -> str:
        """生成缓存键"""
        h = tuple(sorted(hole_cards))
        b = tuple(sorted(board_cards))
        return f"{h}|{b}"


# ── 信息集 ──────────────────────────────────────────────

@dataclass(frozen=True)
class InfoSet:
    """
    信息集 (Information Set)

    CFR的核心概念：玩家在做决策时能观察到的所有信息的集合
    同一InfoSet下的不同真实状态对玩家不可区分

    组成:
    - player: 哪个玩家 (0 or 1 for HU)
    - card_bucket: 牌面抽象bucket
    - street: 当前街道
    - action_history: 动作历史序列的hash
    """
    player: int
    card_bucket: int
    street: str       # "preflop" / "flop" / "turn" / "river"
    action_history: str = ""  # 动作历史的hash字符串

    def __str__(self) -> str:
        return f"IS(p{self.player},{self.street},b{self.card_bucket},{self.action_history[:8]})"


def compute_action_history_hash(actions: List[str]) -> str:
    """将动作历史列表压缩为短hash"""
    if not actions:
        return ""
    raw = "|".join(actions)
    return hashlib.md5(raw.encode()).hexdigest()[:12]
