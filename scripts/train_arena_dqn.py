#!/usr/bin/env python3
"""
用 Arena 的 GameEngine 重新训练 DQN 模型。

背景：NeuralStrategy 使用的 RLCard DQN 模型（54 维观测、2 人近限注）
在 Arena（2-6 人无限注、92 维观测）中从不加注。本脚本用 Arena 的
GameEngine 包装成 Gym 风格 env，训练 92 维 Double DQN 模型。

用法：
    uv run python scripts/train_arena_dqn.py --episodes 100       # 小规模测试
    uv run python scripts/train_arena_dqn.py                       # 默认 50000 集
"""

import argparse
import os
import random
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from treys import Card, Deck, Evaluator

# ────────────────────────────────────────────
# 导入项目模块
# ────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.platforms.arena.game import GameEngine, Street, ActionType, PlayerState
from src.strategies.utils.equity import EquityCalculator
from src.strategies.utils.board_analyzer import BoardAnalyzer
from src.strategies.utils.preflop_range import PreflopRangeManager
from src.strategies.utils.position import normalize_hand_string


# ═══════════════════════════════════════════════════════════════
# QNet — 与 NeuralStrategy 完全一致的架构
# ═══════════════════════════════════════════════════════════════

class QNet(nn.Module):
    def __init__(self, num_actions: int = 5, state_shape: int = 92,
                 mlp_layers: list = None):
        super().__init__()
        if mlp_layers is None:
            mlp_layers = [512, 512]
        self.num_actions = num_actions
        self.state_shape = state_shape
        self.mlp_layers = mlp_layers

        input_dim = state_shape
        layer_dims = [input_dim] + mlp_layers

        fc = [nn.Flatten()]
        fc.append(nn.BatchNorm1d(layer_dims[0]))
        for i in range(len(layer_dims) - 1):
            fc.append(nn.Linear(layer_dims[i], layer_dims[i + 1], bias=True))
            fc.append(nn.Tanh())
        fc.append(nn.Linear(layer_dims[-1], self.num_actions, bias=True))
        self.fc_layers = nn.Sequential(*fc)

    def forward(self, s: torch.Tensor) -> torch.Tensor:
        return self.fc_layers(s)


# ═══════════════════════════════════════════════════════════════
# ObsBuilder — GameEngine 状态 → 92 维观测向量
# 严格对齐 NeuralStrategy._state_to_obs_v2()
# ═══════════════════════════════════════════════════════════════

class ObsBuilder:
    """从 GameEngine 状态构建 92 维观测向量"""

    OBS_DIM = 92

    suit_map = {'s': 0, 'h': 1, 'd': 2, 'c': 3}
    rank_map = {
        'A': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6,
        '8': 7, '9': 8, 'T': 9, 'J': 10, 'Q': 11, 'K': 12,
    }

    # 位置映射 — 与 _state_to_obs_v2 的 pos_map 一致
    pos_map = {"EP": 0, "UTG": 0, "MP": 1, "LP": 2, "BTN": 3, "SB": 4, "BB": 5}
    street_map = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}

    def __init__(self):
        self.equity_calc = EquityCalculator()
        self.board_analyzer = BoardAnalyzer()
        self.range_mgr = PreflopRangeManager()

    def build(self, engine: GameEngine, player_idx: int) -> np.ndarray:
        """构建 player_idx 视角的 92 维观测向量"""
        obs = np.zeros(self.OBS_DIM, dtype=np.float32)
        p = engine.players[player_idx]
        bb = max(engine.big_blind, 1)
        pot = max(engine.pot, 1)

        # ── 特征组 1: 牌面 one-hot (52 维, obs[0:52]) ──
        hole_strs = [Card.int_to_str(c) for c in p.hole_cards] if p.hole_cards else []
        comm_strs = [Card.int_to_str(c) for c in engine.community_cards] if engine.community_cards else []
        all_cards = hole_strs + comm_strs
        for card in all_cards:
            if len(card) >= 2:
                rank_char = card[0]
                suit_char = card[1]
                if rank_char in self.rank_map and suit_char in self.suit_map:
                    idx = self.suit_map[suit_char] * 13 + self.rank_map[rank_char]
                    if idx < 52:
                        obs[idx] = 1.0

        # ── 特征组 2: 我的已下注/BB (obs[52]) ──
        obs[52] = float(p.bet_this_street) / bb

        # ── 特征组 3: 对手最大下注/BB (obs[53]) ──
        opp_max_bet = 0
        for i, op in enumerate(engine.players):
            if i != player_idx and op.is_active:
                opp_max_bet = max(opp_max_bet, op.bet_this_street)
        obs[53] = float(opp_max_bet) / bb

        # ── 特征组 4: log 底池 (obs[54]) ──
        obs[54] = np.log1p(float(pot)) / 10.0

        # ── 特征组 5: to_call/pot (obs[55]) ──
        to_call = engine.current_bet - p.bet_this_street
        obs[55] = float(to_call) / pot if pot > 0 else 0.0

        # ── 特征组 6: 底池赔率 (obs[56]) ──
        obs[56] = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.0

        # ── 特征组 7: SPR (obs[57]) ──
        spr = p.stack / pot if pot > 0 else 20.0
        obs[57] = min(max(spr, 0.0), 20.0) / 20.0

        # ── 特征组 8: 位置 one-hot (6 维, obs[58:64]) ──
        pos_code = self._get_position_code(engine, player_idx)
        pos_idx = self.pos_map.get(pos_code, -1)
        if pos_idx >= 0:
            obs[58 + pos_idx] = 1.0

        # ── 特征组 9: 街道 one-hot (4 维, obs[64:68]) ──
        street_name = self._get_street_name(engine)
        street_idx = self.street_map.get(street_name, 0)
        obs[64 + street_idx] = 1.0

        # ── 特征组 10: 对手数/9 (obs[68]) ──
        num_opp = sum(
            1 for i, op in enumerate(engine.players)
            if i != player_idx and op.is_active and not op.is_all_in
        )
        obs[68] = float(num_opp) / 9.0

        # ── 特征组 11: can_raise / can_call (obs[69:71]) ──
        min_raise_total = engine.current_bet + engine.min_raise
        obs[69] = 1.0 if p.stack + p.bet_this_street >= min_raise_total else 0.0  # can_raise
        obs[70] = 1.0 if p.stack >= to_call else 0.0  # can_call

        # ── 特征组 12: 对手均 VPIP (obs[71]) ──
        # 训练时无对手统计，用默认值
        obs[71] = 0.3

        # ── 特征组 13: 牌面湿润度 (obs[72]) ──
        if comm_strs:
            texture = self.board_analyzer.analyze(comm_strs)
            obs[72] = texture.get("wetness", 0.0)
        else:
            obs[72] = 0.0

        # ── 特征组 14: 预估胜率 (obs[73]) ──
        if hole_strs:
            try:
                obs[73] = self.equity_calc.calculate_equity(
                    hole_strs, comm_strs, num_opp if num_opp > 0 else 1, iterations=200
                )
            except Exception:
                obs[73] = 0.0
        else:
            obs[73] = 0.0

        # ── 特征组 15: 翻前牌力等级 one-hot (4 维, obs[74:78]) ──
        hand_str = normalize_hand_string(hole_strs) if len(hole_strs) >= 2 else "XX"
        tier = self.range_mgr.get_hand_tier(hand_str)
        obs[74 + min(tier, 3)] = 1.0

        # ── 特征组 16: 保留 (14 维, obs[78:92]) — 零 ──
        # 已预分配零

        return obs

    # ── 内部辅助 ──

    def _get_position_code(self, engine: GameEngine, player_idx: int) -> str:
        """复刻 get_position_code 的 dist 逻辑"""
        num_players = len(engine.players)
        active_seats = [i for i in range(num_players) if engine.players[i].stack > 0]
        if len(active_seats) < 2:
            return "ALL"

        try:
            my_idx = active_seats.index(player_idx)
            dealer_idx = active_seats.index(engine.dealer_idx)
        except ValueError:
            return "ALL"

        dist = (my_idx - dealer_idx + len(active_seats)) % len(active_seats)

        if dist == 0:
            return "LP"
        if dist == 1:
            return "SB"
        if dist == 2:
            return "BB"

        if len(active_seats) <= 3:
            return "LP" if dist == 0 else "EP"

        if dist <= len(active_seats) // 3:
            return "EP"
        if dist <= 2 * len(active_seats) // 3:
            return "MP"
        return "LP"

    def _get_street_name(self, engine: GameEngine) -> str:
        street = engine.current_street
        if street == Street.PREFLOP:
            return "preflop"
        if street == Street.FLOP:
            return "flop"
        if street == Street.TURN:
            return "turn"
        if street == Street.RIVER:
            return "river"
        return "preflop"


# ═══════════════════════════════════════════════════════════════
# ActionTranslator — 5 离散动作 → GameEngine (ActionType, amount)
# 对齐 NeuralStrategy._map_action_to_plan()
# ═══════════════════════════════════════════════════════════════

class ActionTranslator:
    """
    5 个离散动作索引映射：

    | 索引 | 含义         | GameEngine 映射                                           |
    |------|-------------|----------------------------------------------------------|
    | 0    | fold/check  | FOLD(to_call>0) / CHECK(to_call=0)                        |
    | 1    | call/check  | CALL(to_call>0) / CHECK(to_call=0); stack不足→ALL_IN      |
    | 2    | raise 0.5p  | RAISE, total=bet+to_call+int(pot*0.5); clamp; 不足→ALL_IN |
    | 3    | raise pot   | RAISE, total=bet+to_call+int(pot*1.0); clamp; 不足→ALL_IN |
    | 4    | all-in      | ALL_IN                                                    |
    """

    @staticmethod
    def translate(action_idx: int, engine: GameEngine,
                  player_idx: int) -> Tuple[ActionType, int]:
        p = engine.players[player_idx]
        to_call = engine.current_bet - p.bet_this_street
        pot = engine.pot

        if action_idx == 0:
            # fold / check
            if to_call > 0:
                return ActionType.FOLD, 0
            return ActionType.CHECK, 0

        if action_idx == 1:
            # call / check
            if to_call <= 0:
                return ActionType.CHECK, 0
            if p.stack < to_call:
                return ActionType.ALL_IN, 0
            return ActionType.CALL, 0

        if action_idx == 2:
            # raise half pot
            total_bet = p.bet_this_street + to_call + max(1, int(pot * 0.5))
            return ActionTranslator._resolve_raise(engine, player_idx, total_bet)

        if action_idx == 3:
            # raise pot
            total_bet = p.bet_this_street + to_call + max(1, int(pot * 1.0))
            return ActionTranslator._resolve_raise(engine, player_idx, total_bet)

        if action_idx == 4:
            # all-in
            return ActionType.ALL_IN, 0

        # fallback
        return ActionType.CHECK, 0

    @staticmethod
    def _resolve_raise(engine: GameEngine, player_idx: int,
                       total_bet: int) -> Tuple[ActionType, int]:
        p = engine.players[player_idx]
        min_required = p.bet_this_street + (engine.current_bet - p.bet_this_street) + engine.min_raise
        total_bet = max(total_bet, min_required)

        if p.stack + p.bet_this_street < total_bet:
            return ActionType.ALL_IN, 0
        return ActionType.RAISE, total_bet


# ═══════════════════════════════════════════════════════════════
# LegalActionMask — 精确合法动作掩码
# ═══════════════════════════════════════════════════════════════

class LegalActionMask:
    NUM_ACTIONS = 5

    @staticmethod
    def get_mask(engine: GameEngine, player_idx: int) -> np.ndarray:
        """
        返回 shape=(5,) 的 bool 数组，True 表示该动作合法。

        | 索引 | 动作        | 合法条件                                           |
        |------|------------|---------------------------------------------------|
        | 0    | fold/check | 始终合法                                            |
        | 1    | call/check | to_call=0 或 stack>0                                |
        | 2    | raise 0.5p | stack+bet_this_street >= current_bet + min_raise    |
        | 3    | raise pot  | 同上                                                |
        | 4    | all-in     | stack>0 且（tier<=2 或 SPR<2 或 stack<3BB）         |
        """
        mask = np.zeros(LegalActionMask.NUM_ACTIONS, dtype=bool)
        p = engine.players[player_idx]

        # 0: fold/check — 始终合法
        mask[0] = True

        # 1: call/check
        to_call = engine.current_bet - p.bet_this_street
        mask[1] = (to_call <= 0) or (p.stack > 0)

        # 2, 3: raise half pot / raise pot
        min_raise_total = engine.current_bet + engine.min_raise
        can_raise = (p.stack + p.bet_this_street) >= min_raise_total
        mask[2] = can_raise
        mask[3] = can_raise

        # 4: all-in — 限制：只有强牌、短筹码、或 stack<3BB 时可选
        if p.stack > 0:
            # 短筹码保护（stack 不到 3BB → 推了合理）
            if p.stack <= engine.big_blind * 3:
                mask[4] = True
            else:
                # SPR < 2 → 推了合理
                pot = max(engine.pot, 1)
                spr = p.stack / pot
                if spr < 2.0:
                    mask[4] = True
                else:
                    # 强牌（tier 1-2）才允许全下
                    hole_strs = [Card.int_to_str(c) for c in p.hole_cards] if p.hole_cards else []
                    hand_str = normalize_hand_string(hole_strs) if len(hole_strs) >= 2 else "XX"
                    if not hasattr(LegalActionMask, '_range_mgr'):
                        LegalActionMask._range_mgr = PreflopRangeManager()
                    tier = LegalActionMask._range_mgr.get_hand_tier(hand_str)
                    mask[4] = tier <= 2

        return mask


# ═══════════════════════════════════════════════════════════════
# ArenaPokerEnv — GameEngine → step/reset 包装
# ═══════════════════════════════════════════════════════════════

class ArenaPokerEnv:
    """将 GameEngine 包装成 Gym 风格的 step()/reset() 接口

    seat 0 是 DQN 学习者（由外部 trainer 控制），
    其余座位用已有策略（Balanced/Aggressive/Range/CheckOrFold）自动行动。
    这样 DQN 学的是"如何击败不同风格的对手"，而非自对弈。
    """

    def __init__(self, initial_stack: int = 200, sb: int = 1, bb: int = 2):
        self.initial_stack = initial_stack
        self.sb = sb
        self.bb = bb
        self.engine: Optional[GameEngine] = None
        self.obs_builder = ObsBuilder()

        # 当前行动玩家
        self.current_actor: int = 0
        # 街道内已行动记录
        self.acted_this_street: set = set()
        # 手牌开始时的筹码快照（用于算 reward）
        self.hand_start_stacks: Dict[int, int] = {}
        # 手牌是否结束
        self.hand_done: bool = False
        # 最终奖励
        self.rewards: Dict[int, float] = {}
        # 防死循环计数
        self._step_count: int = 0
        self._max_steps_per_hand: int = 150  # 安全阈值

        # 对手策略池（seat 1+ 使用）
        self._opponent_strategies = self._create_opponent_pool()
        # 当前座位 → 策略映射
        self._seat_strategies: Dict[int, Strategy] = {}

    def _create_opponent_pool(self) -> list:
        """创建对手策略池，每手牌随机分配"""
        from src.strategies.strategies.balanced import BalancedStrategy
        from src.strategies.strategies.aggressive import AggressiveStrategy
        from src.strategies.strategies.range import RangeStrategy
        from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
        return [
            BalancedStrategy(thinking_timeout=0.01),
            AggressiveStrategy(thinking_timeout=0.01),
            RangeStrategy(),
            CheckOrFoldStrategy(),
        ]

    def _assign_opponents(self, num_players: int):
        """为 seat 1+ 随机分配策略"""
        self._seat_strategies = {}
        for seat in range(1, num_players):
            self._seat_strategies[seat] = random.choice(self._opponent_strategies)

    def _opponent_act(self, player_idx: int) -> Tuple[ActionType, int]:
        """对手策略决策，返回 (ArenaActionType, amount)"""
        from src.strategies.game_state import GameState as StrategyGameState, Player as StrategyPlayer
        from src.strategies.action_plan import ActionType as StrategyActionType

        strategy = self._seat_strategies.get(player_idx)
        if strategy is None:
            # fallback: check/fold
            p = self.engine.players[player_idx]
            to_call = self.engine.current_bet - p.bet_this_street
            if to_call == 0:
                return ActionType.CHECK, 0
            return ActionType.FOLD, 0

        # 构造策略层 GameState（简化版，只填必要字段）
        p = self.engine.players[player_idx]
        gs = StrategyGameState()
        gs.my_seat_id = player_idx
        gs.hole_cards = [Card.int_to_str(c) for c in p.hole_cards] if p.hole_cards else []
        gs.community_cards = [Card.int_to_str(c) for c in self.engine.community_cards] if self.engine.community_cards else []
        gs.pot = self.engine.pot
        gs.to_call = self.engine.current_bet - p.bet_this_street
        gs.min_raise = self.engine.min_raise
        gs.max_raise = p.stack + p.bet_this_street
        gs.big_blind = self.engine.big_blind
        gs.total_chips = p.stack

        for i, pa in enumerate(self.engine.players):
            sp = StrategyPlayer(
                seat_id=pa.seat_id,
                name=pa.name,
                chips=pa.stack,
                is_active=pa.is_active,
                status="active" if pa.is_active else "folded",
                bet=pa.bet_this_street,
            )
            if pa.is_all_in:
                sp.status = "all_in"
            gs.players[pa.seat_id] = sp

        plan = strategy.make_decision(gs)
        to_call = self.engine.current_bet - p.bet_this_street
        strategy_action, amount = plan.get_action_for_bet(to_call, self.engine.pot)

        # 转换动作类型
        action_map = {
            StrategyActionType.FOLD: ActionType.FOLD,
            StrategyActionType.CHECK: ActionType.CHECK,
            StrategyActionType.CALL: ActionType.CALL,
            StrategyActionType.RAISE: ActionType.RAISE,
            StrategyActionType.ALL_IN: ActionType.ALL_IN,
        }
        arena_action = action_map.get(strategy_action, ActionType.CHECK)

        # RAISE 的 amount 转换：策略层返回的是加注增量，GameEngine 需要总注额
        if arena_action == ActionType.RAISE and amount > 0:
            total_bet = p.bet_this_street + to_call + amount
            min_required = p.bet_this_street + to_call + self.engine.min_raise
            amount = max(total_bet, min_required)

        return arena_action, amount

    def reset(self, num_players: int = 2) -> np.ndarray:
        """重置一手牌，返回当前行动者的观测"""
        players_info = [
            {"name": f"P{i}", "stack": self.initial_stack}
            for i in range(num_players)
        ]
        self.engine = GameEngine(players_info, self.sb, self.bb)

        # 为 seat 1+ 分配对手策略
        self._assign_opponents(num_players)

        dealer_idx = random.randint(0, num_players - 1)
        self.engine.reset_hand(dealer_idx)
        self.engine.deal_hole_cards()

        first_actor = self.engine.post_blinds()

        # 记录手牌开始时的筹码（不含盲注投入——盲注已在 post_blinds 中扣除）
        self.hand_start_stacks = {
            i: p.stack + p.total_investment for i, p in enumerate(self.engine.players)
        }

        self.acted_this_street = set()
        self.hand_done = False
        self.rewards = {}
        self._step_count = 0

        # 先执行所有对手的连续动作，直到轮到 seat 0 或手牌结束
        self.current_actor = self._find_next_actor(first_actor)
        self._run_opponents_until_hero()

        if self.hand_done or self.current_actor is None:
            return np.zeros(ObsBuilder.OBS_DIM, dtype=np.float32)

        # 只在轮到 seat 0 时返回观测
        return self.obs_builder.build(self.engine, self.current_actor)

    def _run_opponents_until_hero(self):
        """自动执行对手动作，直到轮到 seat 0（DQN 学习者）或手牌结束"""
        max_auto_steps = 50  # 防死循环
        for _ in range(max_auto_steps):
            if self.hand_done or self.current_actor is None:
                return
            if self.current_actor == 0:
                return  # 轮到 DQN 学习者，停

            # 对手自动行动
            opp_action, opp_amount = self._opponent_act(self.current_actor)
            self._execute_and_advance(opp_action, opp_amount)

    def _execute_and_advance(self, action_type: ActionType, amount: int):
        """执行一个动作并推进状态（对手和 DQN 共用）"""
        self._step_count += 1

        # 维护 acted_this_street
        self.acted_this_street.add(self.current_actor)
        if action_type in (ActionType.RAISE, ActionType.ALL_IN):
            for i in range(len(self.engine.players)):
                if i != self.current_actor:
                    self.acted_this_street.discard(i)

        self.engine.execute_action(self.current_actor, action_type, amount)

        # 安全检查
        if self._step_count >= self._max_steps_per_hand:
            self._advance_to_showdown()
            self._finish_hand()
            return

        # 检查只剩 ≤1 人活跃
        if self._count_active() <= 1:
            self._finish_hand()
            return

        # 判定街道是否结束
        if self._is_street_complete():
            self.acted_this_street = set()
            if self.engine.current_street >= Street.RIVER or self._count_can_act() <= 1:
                self._advance_to_showdown()
                self._finish_hand()
                return
            self.engine.next_street()

        # 找下一个行动者
        next_actor = self._find_next_actor((self.current_actor + 1) % len(self.engine.players))
        if next_actor is None:
            self._advance_to_showdown()
            self._finish_hand()
            return

        self.current_actor = next_actor

    def step(self, action_idx: int) -> Tuple[np.ndarray, float, bool, dict]:
        """
        seat 0 (DQN 学习者) 执行动作，然后自动跑完所有对手的连续动作，
        直到再次轮到 seat 0 或手牌结束。

        返回 (obs, intermediate_reward, done, info)
        """
        if self.hand_done or self.current_actor is None:
            return np.zeros(ObsBuilder.OBS_DIM, dtype=np.float32), 0.0, True, {}

        assert self.current_actor == 0, f"step() 只在 seat 0 行动时调用，当前 actor={self.current_actor}"

        # 1. 翻译 DQN 动作
        action_type, amount = ActionTranslator.translate(
            action_idx, self.engine, self.current_actor
        )

        # 2. 计算中间奖励
        intermediate_reward = self._calc_intermediate_reward(action_idx, action_type)

        # 3. 执行 DQN 动作并推进状态
        self._execute_and_advance(action_type, amount)

        if self.hand_done:
            return np.zeros(ObsBuilder.OBS_DIM, dtype=np.float32), intermediate_reward, True, {
                "rewards": self.rewards
            }

        # 4. 自动执行对手动作，直到轮到 seat 0 或手牌结束
        self._run_opponents_until_hero()

        if self.hand_done or self.current_actor is None:
            return np.zeros(ObsBuilder.OBS_DIM, dtype=np.float32), intermediate_reward, True, {
                "rewards": self.rewards
            }

        # 5. 轮到 seat 0，返回观测
        obs = self.obs_builder.build(self.engine, self.current_actor)
        return obs, intermediate_reward, False, {}

    # ── 街道完成判定 ──

    def _is_street_complete(self) -> bool:
        """参考 Competition._betting_loop 的 acted[] 逻辑"""
        num_players = len(self.engine.players)

        # 只剩 0-1 人能行动 → 街道结束
        if self._count_can_act() <= 1:
            return True

        # 所有人都行动过且 bet_this_street == current_bet
        for i in range(num_players):
            p = self.engine.players[i]
            if not p.is_active or p.is_all_in:
                continue
            if i not in self.acted_this_street:
                return False
            if p.bet_this_street != self.engine.current_bet:
                return False

        return True

    # ── 辅助方法 ──

    def _count_active(self) -> int:
        return sum(1 for p in self.engine.players if p.is_active)

    def _count_can_act(self) -> int:
        return sum(
            1 for p in self.engine.players
            if p.is_active and not p.is_all_in
        )

    def _find_next_actor(self, start_idx: int) -> Optional[int]:
        """从 start_idx 开始顺时针找下一个能行动的玩家"""
        n = len(self.engine.players)
        for offset in range(n):
            idx = (start_idx + offset) % n
            p = self.engine.players[idx]
            if p.is_active and not p.is_all_in:
                return idx
        return None

    def _calc_intermediate_reward(self, action_idx: int, action_type: ActionType) -> float:
        """中间奖励（action shaping）— 简单版：只奖励好牌加注、惩罚弱牌入池"""
        p = self.engine.players[self.current_actor]
        to_call = self.engine.current_bet - p.bet_this_street
        reward = 0.0

        # 翻前牌力评估
        hole_strs = [Card.int_to_str(c) for c in p.hole_cards] if p.hole_cards else []
        hand_str = normalize_hand_string(hole_strs) if len(hole_strs) >= 2 else "XX"

        if not hasattr(self, '_range_mgr_cached'):
            self._range_mgr_cached = PreflopRangeManager()
        tier = self._range_mgr_cached.get_hand_tier(hand_str)

        if action_idx == 0:
            # fold — to_call>0 时弃牌合理，小鼓励
            reward = 0.0 if to_call == 0 else 0.05

        elif action_idx == 1:
            # call — 强牌跟注好，弱牌跟注不好
            if to_call == 0:
                reward = 0.0
            elif tier <= 2:
                reward = 0.1
            elif tier <= 3:
                reward = 0.0
            else:
                reward = -0.1

        elif action_idx in (2, 3):
            # raise — 强牌加注好，弱牌加注不好
            if tier <= 2:
                reward = 0.2
            elif tier <= 3:
                reward = 0.05
            else:
                reward = -0.15

        elif action_idx == 4:
            # all-in — 掩码已限制只有 tier<=2/短筹码可选
            reward = 0.0

        return reward

    def _advance_to_showdown(self):
        """推进到摊牌阶段（如果还没到）"""
        while self.engine.current_street < Street.RIVER:
            self.engine.next_street()
        # river 已经在 _finish_hand 中通过 get_winners 处理

    def _finish_hand(self):
        """结算手牌：分配筹码、计算 reward"""
        self.hand_done = True

        winners = self.engine.get_winners()
        for seat_id, amount in winners:
            self.engine.players[seat_id].stack += amount

        # reward = (final_stack - hand_start_stack) / bb, clip [-10, 10]
        for i, p in enumerate(self.engine.players):
            start = self.hand_start_stacks.get(i, self.initial_stack)
            delta = p.stack - start
            self.rewards[i] = float(np.clip(delta / self.bb, -10.0, 10.0))


# ═══════════════════════════════════════════════════════════════
# ReplayBuffer — 经验回放池
# ═══════════════════════════════════════════════════════════════

class ReplayBuffer:
    def __init__(self, capacity: int = 100000):
        self.capacity = capacity
        self.buffer: deque = deque(maxlen=capacity)

    def push(self, obs: np.ndarray, action: int, reward: float,
             next_obs: np.ndarray, done: bool, legal_mask: np.ndarray):
        self.buffer.append((obs, action, reward, next_obs, done, legal_mask))

    def sample(self, batch_size: int) -> Tuple[
        np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray
    ]:
        batch = random.sample(self.buffer, batch_size)
        obs, actions, rewards, next_obs, dones, masks = zip(*batch)
        return (
            np.array(obs, dtype=np.float32),
            np.array(actions, dtype=np.int64),
            np.array(rewards, dtype=np.float32),
            np.array(next_obs, dtype=np.float32),
            np.array(dones, dtype=np.float32),
            np.array(masks, dtype=np.float32),
        )

    def __len__(self) -> int:
        return len(self.buffer)


# ═══════════════════════════════════════════════════════════════
# DQNTrainer — QNet + target net + Double DQN + ε-greedy
# ═══════════════════════════════════════════════════════════════

class DQNTrainer:
    def __init__(
        self,
        state_dim: int = 92,
        num_actions: int = 5,
        lr: float = 1e-4,
        gamma: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.9999,
        target_update_freq: int = 1000,
        device: str = "",
    ):
        if device == "":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.q_net = QNet(num_actions=num_actions, state_shape=state_dim).to(self.device)
        self.target_net = QNet(num_actions=num_actions, state_shape=state_dim).to(self.device)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.q_net.parameters(), lr=lr)
        self.gamma = gamma

        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay

        self.target_update_freq = target_update_freq
        self.train_step_count = 0

        # 统计
        self.total_loss = 0.0
        self.loss_count = 0

    def select_action(self, obs: np.ndarray, legal_mask: np.ndarray) -> int:
        """ε-greedy 动作选择，只从合法动作中选"""
        if random.random() < self.epsilon:
            # 从合法动作中随机选
            legal_indices = np.where(legal_mask)[0]
            return int(random.choice(legal_indices))

        with torch.no_grad():
            self.q_net.eval()
            obs_t = torch.from_numpy(obs).unsqueeze(0).to(self.device)
            q_values = self.q_net(obs_t).squeeze(0)
            self.q_net.train()

            # 掩码非法动作
            masked_q = q_values.clone()
            for a in range(len(legal_mask)):
                if not legal_mask[a]:
                    masked_q[a] = -1e9

            return int(torch.argmax(masked_q).item())

    def train_step(self, buffer: ReplayBuffer, batch_size: int = 256) -> float:
        """Double DQN 训练一步"""
        if len(buffer) < batch_size:
            return 0.0

        obs, actions, rewards, next_obs, dones, masks = buffer.sample(batch_size)

        obs_t = torch.from_numpy(obs).to(self.device)
        actions_t = torch.from_numpy(actions).unsqueeze(1).to(self.device)
        rewards_t = torch.from_numpy(rewards).unsqueeze(1).to(self.device)
        next_obs_t = torch.from_numpy(next_obs).to(self.device)
        dones_t = torch.from_numpy(dones).unsqueeze(1).to(self.device)
        masks_t = torch.from_numpy(masks).to(self.device)

        # 当前 Q 值
        current_q = self.q_net(obs_t).gather(1, actions_t)

        # Double DQN: 主网络选动作，目标网络算 Q 值
        with torch.no_grad():
            next_q_main = self.q_net(next_obs_t)
            # 掩码非法动作
            next_q_main_masked = next_q_main.clone()
            next_q_main_masked[masks_t == 0] = -1e9
            next_actions = next_q_main_masked.argmax(dim=1, keepdim=True)

            next_q_target = self.target_net(next_obs_t).gather(1, next_actions)
            target_q = rewards_t + (1 - dones_t) * self.gamma * next_q_target

        # Huber loss
        loss = nn.SmoothL1Loss()(current_q, target_q)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q_net.parameters(), 10.0)
        self.optimizer.step()

        self.train_step_count += 1
        self.total_loss += loss.item()
        self.loss_count += 1

        # 更新目标网络
        if self.train_step_count % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())

        return loss.item()

    def avg_loss(self) -> float:
        if self.loss_count == 0:
            return 0.0
        return self.total_loss / self.loss_count

    def reset_loss_stats(self):
        self.total_loss = 0.0
        self.loss_count = 0

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save(self.q_net.state_dict(), path)
        print(f"模型已保存至: {path}")


# ═══════════════════════════════════════════════════════════════
# 训练主循环
# ═══════════════════════════════════════════════════════════════

def train(
    num_episodes: int = 100000,
    initial_stack: int = 200,
    sb: int = 1,
    bb: int = 2,
    lr: float = 1e-4,
    gamma: float = 0.99,
    buffer_size: int = 200000,
    batch_size: int = 256,
    epsilon_start: float = 1.0,
    epsilon_end: float = 0.05,
    epsilon_decay: float = 0.99995,
    target_update_freq: int = 1000,
    train_steps_per_episode: int = 2,
    save_path: str = "data/models/nlh_dqn.pth",
    checkpoint_interval: int = 10000,
    log_interval: int = 500,
):
    env = ArenaPokerEnv(initial_stack=initial_stack, sb=sb, bb=bb)
    buffer = ReplayBuffer(capacity=buffer_size)
    trainer = DQNTrainer(
        state_dim=92,
        num_actions=5,
        lr=lr,
        gamma=gamma,
        epsilon_start=epsilon_start,
        epsilon_end=epsilon_end,
        epsilon_decay=epsilon_decay,
        target_update_freq=target_update_freq,
    )

    print(f"开始 Arena DQN 训练: {num_episodes} 集, 初始筹码={initial_stack} ({initial_stack // bb}BB)")
    print(f"设备: {trainer.device}")
    start_time = time.time()

    # 统计
    episode_rewards = deque(maxlen=log_interval)
    action_counts = np.zeros(5, dtype=int)  # 统计各动作频率

    for episode in range(1, num_episodes + 1):
        num_players = random.choice([2, 3, 4, 5, 6])
        obs = env.reset(num_players)

        # 只有 seat 0 (DQN) 的决策需要记录
        transitions = []
        done = env.hand_done
        info = {}

        while not done:
            legal_mask = LegalActionMask.get_mask(env.engine, env.current_actor)
            action = trainer.select_action(obs, legal_mask)
            action_counts[action] += 1

            next_obs, intermediate_reward, done, info = env.step(action)
            transitions.append((obs.copy(), action, next_obs.copy(), done, legal_mask.copy(), intermediate_reward))
            obs = next_obs

        # 手牌结束：组合中间奖励 + 终局筹码变化奖励
        # seat 0 的终局奖励
        final_rewards = info.get("rewards", env.rewards)
        hero_final_reward = final_rewards.get(0, 0.0)
        gamma = trainer.gamma
        n_trans = len(transitions)

        for i, (t_obs, t_action, t_next_obs, t_done, t_mask, t_inter) in enumerate(transitions):
            # 该 transition 到手牌结束的步数
            steps_to_end = n_trans - i - 1
            discount = gamma ** max(steps_to_end, 0)
            combined_reward = t_inter + discount * hero_final_reward
            buffer.push(t_obs, t_action, combined_reward, t_next_obs, t_done, t_mask)

        # 记录 hero 终局奖励
        episode_rewards.append(hero_final_reward)

        # 训练：buffer 足够后每集训练多步，加速收敛
        if len(buffer) >= batch_size:
            for _ in range(train_steps_per_episode):
                trainer.train_step(buffer, batch_size)

        # 衰减 ε（按集数，非按 train_step）
        trainer.epsilon = max(trainer.epsilon_end, trainer.epsilon * trainer.epsilon_decay)

        # 日志
        if episode % log_interval == 0:
            elapsed = time.time() - start_time
            avg_r = np.mean(episode_rewards) if episode_rewards else 0.0
            avg_l = trainer.avg_loss()
            total_actions = action_counts.sum()
            raise_freq = (action_counts[2] + action_counts[3] + action_counts[4]) / total_actions * 100 if total_actions > 0 else 0.0

            print(
                f"[Ep {episode:>6d}/{num_episodes}] "
                f"avg_reward={avg_r:+.3f} "
                f"avg_loss={avg_l:.4f} "
                f"ε={trainer.epsilon:.4f} "
                f"raise%={raise_freq:.1f}% "
                f"buffer={len(buffer)} "
                f"耗时={elapsed:.0f}s"
            )
            trainer.reset_loss_stats()

        # 检查点保存
        if episode % checkpoint_interval == 0:
            ckpt_path = save_path.replace(".pth", f"_ep{episode}.pth")
            trainer.save(ckpt_path)
            # 同时覆盖主模型
            trainer.save(save_path)

    # 最终保存
    trainer.save(save_path)
    elapsed = time.time() - start_time
    print(f"\n训练完成！总耗时: {elapsed:.0f}s, 模型已保存至: {save_path}")

    # 最终动作频率统计
    total = action_counts.sum()
    if total > 0:
        labels = ["fold/check", "call/check", "raise_0.5p", "raise_pot", "all_in"]
        print("动作频率统计:")
        for i, label in enumerate(labels):
            print(f"  {label}: {action_counts[i] / total * 100:.1f}% ({action_counts[i]})")


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="用 Arena GameEngine 训练 DQN 模型")
    parser.add_argument("--episodes", type=int, default=100000, help="训练集数 (默认 100000)")
    parser.add_argument("--initial-stack", type=int, default=200, help="初始筹码 (默认 200, 即 100BB)")
    parser.add_argument("--lr", type=float, default=1e-4, help="学习率 (默认 1e-4)")
    parser.add_argument("--batch-size", type=int, default=256, help="批次大小 (默认 256)")
    parser.add_argument("--buffer-size", type=int, default=200000, help="回放池大小 (默认 200000)")
    parser.add_argument("--save-path", type=str, default="data/models/nlh_dqn.pth", help="模型保存路径")
    parser.add_argument("--checkpoint-interval", type=int, default=10000, help="检查点保存间隔 (默认 10000)")
    parser.add_argument("--train-steps", type=int, default=2, help="每集训练步数 (默认 2)")
    parser.add_argument("--log-interval", type=int, default=500, help="日志打印间隔 (默认 500)")
    args = parser.parse_args()

    train(
        num_episodes=args.episodes,
        initial_stack=args.initial_stack,
        lr=args.lr,
        batch_size=args.batch_size,
        buffer_size=args.buffer_size,
        train_steps_per_episode=args.train_steps,
        save_path=args.save_path,
        checkpoint_interval=args.checkpoint_interval,
        log_interval=args.log_interval,
    )
