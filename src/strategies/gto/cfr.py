"""
CFR核心算法实现

三种变体：
1. VanillaCFR:  基础反事实遗憾最小化 (Zinkevich 2007)
2. CFRPlus:     遗憾匹配+，负遗憾清零 (Tammelin 2015)
3. MCCFR:       蒙特卡洛CFR，采样部分博弈树 (Lanctot 2009)

训练输出：策略表 {info_set: {action: probability}}
可导出为 gto_tables.yaml 供阶段1查表使用
"""
from __future__ import annotations

import copy
import random
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .abstraction import InfoSet, ActionAbstraction, CardAbstraction, compute_action_history_hash
from .game_tree import GameTree, TreeNode, NodeType

logger = logging.getLogger("gto.cfr")


# ── 遗憾匹配 ──────────────────────────────────────────

def regret_matching(regrets: Dict[str, float]) -> Dict[str, float]:
    """
    遗憾匹配：将遗憾值转为策略概率

    规则：正遗憾按比例分配，无正遗憾则均匀分布
    """
    positive_regrets = {a: max(0.0, r) for a, r in regrets.items()}
    total = sum(positive_regrets.values())

    if total <= 0:
        # 无正遗憾 → 均匀分布
        n = len(regrets)
        return {a: 1.0 / n for a in regrets} if n > 0 else {}

    return {a: r / total for a, r in positive_regrets.items()}


def regret_matching_plus(regrets: Dict[str, float]) -> Dict[str, float]:
    """
    遗憾匹配+ (CFR+): 负遗憾直接清零后再做匹配

    收敛速度比vanilla CFR快很多
    """
    # CFR+ 在更新阶段就已清零负遗憾，这里等价于regret_matching
    return regret_matching(regrets)


# ── CFR基类 ────────────────────────────────────────────

class CFRBase(ABC):
    """CFR算法基类"""

    def __init__(
        self,
        card_abs: CardAbstraction,
        action_abs: ActionAbstraction,
        small_blind: int = 1,
        big_blind: int = 2,
        starting_stack: int = 100,
    ):
        self.card_abs = card_abs
        self.action_abs = action_abs
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.starting_stack = starting_stack

        # 核心数据结构
        # regret_sum[info_set][action] = 累积遗憾值
        self.regret_sum: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        # strategy_sum[info_set][action] = 累积策略
        self.strategy_sum: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

        # 训练统计
        self.iteration = 0
        self.exploitability_history: List[float] = []

    def _info_set_key(self, info_set: InfoSet) -> str:
        """将InfoSet转为可哈希的字符串键"""
        return f"{info_set.player}|{info_set.street}|{info_set.card_bucket}|{info_set.action_history}"

    def get_strategy(self, info_set: InfoSet, actions: List[str]) -> Dict[str, float]:
        """通过遗憾匹配获取当前策略"""
        key = self._info_set_key(info_set)
        regrets = self.regret_sum[key]
        return regret_matching({a: regrets.get(a, 0.0) for a in actions})

    def get_average_strategy(self, info_set: InfoSet, actions: List[str]) -> Dict[str, float]:
        """获取平均策略（收敛后的近似纳什均衡）"""
        key = self._info_set_key(info_set)
        strategy = self.strategy_sum[key]
        total = sum(strategy.get(a, 0.0) for a in actions)

        if total <= 0:
            n = len(actions)
            return {a: 1.0 / n for a in actions} if n > 0 else {}

        return {a: strategy.get(a, 0.0) / total for a in actions}

    def get_all_average_strategies(self) -> Dict[str, Dict[str, float]]:
        """获取所有信息集的平均策略"""
        result = {}
        for key in self.strategy_sum:
            actions = list(self.strategy_sum[key].keys())
            if actions:
                total = sum(self.strategy_sum[key].values())
                if total > 0:
                    result[key] = {a: v / total for a, v in self.strategy_sum[key].items()}
                else:
                    n = len(actions)
                    result[key] = {a: 1.0 / n for a in actions}
        return result

    @abstractmethod
    def train(self, iterations: int) -> Dict[str, float]:
        """
        运行CFR训练

        Args:
            iterations: 训练迭代次数

        Returns:
            训练统计 {"iteration": N, "exploitability": E, "strategy_size": S}
        """
        pass

    def _update_regrets(self, info_set: InfoSet, actions: List[str],
                        regrets: Dict[str, float], reach_prob: float) -> None:
        """更新累积遗憾值和策略"""
        key = self._info_set_key(info_set)
        strategy = self.get_strategy(info_set, actions)

        for action in actions:
            self.regret_sum[key][action] += regrets.get(action, 0.0) * reach_prob
            self.strategy_sum[key][action] += strategy.get(action, 0.0) * reach_prob


# ── Vanilla CFR ────────────────────────────────────────

class VanillaCFR(CFRBase):
    """
    基础CFR (Counterfactual Regret Minimization)

    每轮迭代遍历整个博弈树，更新每个信息集的遗憾值。
    时间复杂度 O(N * |I| * |A|)，N为迭代数，|I|为信息集数，|A|为行动数
    """

    def train(self, iterations: int) -> Dict[str, float]:
        logger.info(f"VanillaCFR 开始训练，迭代次数: {iterations}")

        for i in range(iterations):
            self.iteration += 1

            # 遍历两种可能的玩家视角
            for player in range(2):
                self._cfr_traverse(
                    player=player,
                    street="preflop",
                    pot=self.small_blind + self.big_blind,
                    stacks=[self.starting_stack - self.small_blind,
                            self.starting_stack - self.big_blind],
                    current_bets=[self.small_blind, self.big_blind],
                    reach_probs=[1.0, 1.0],
                    action_history=[],
                    raise_rounds=0,
                )

            if (i + 1) % max(1, iterations // 10) == 0:
                strategy_size = len(self.strategy_sum)
                logger.info(f"  迭代 {i+1}/{iterations}, 策略表大小: {strategy_size}")

        strategy_size = len(self.strategy_sum)
        logger.info(f"VanillaCFR 训练完成，迭代: {self.iteration}, 策略表大小: {strategy_size}")

        return {
            "iteration": self.iteration,
            "strategy_size": strategy_size,
        }

    # 最大递归深度
    MAX_DEPTH = 15

    def _cfr_traverse(
        self,
        player: int,
        street: str,
        pot: int,
        stacks: List[int],
        current_bets: List[int],
        reach_probs: List[float],
        action_history: List[str],
        raise_rounds: int,
        depth: int = 0,
    ) -> float:
        """
        CFR递归遍历

        Args:
            player: 当前做决策的玩家
            reach_probs: 两个玩家到达此节点的概率

        Returns:
            当前节点的反事实值(counterfactual value)
        """
        # 深度限制
        if depth >= self.MAX_DEPTH:
            return 0.0

        opp = 1 - player
        to_call = max(0, current_bets[opp] - current_bets[player])

        # 获取可执行行动
        actions = self.action_abs.get_abstract_actions(
            pot=pot,
            to_call=to_call,
            min_raise=self.big_blind * 2,
            stack=stacks[player],
            big_blind=self.big_blind,
        )

        action_names = [a[0] for a in actions]

        # 构建信息集
        action_hash = compute_action_history_hash(action_history)
        info_set = InfoSet(
            player=player,
            card_bucket=0,  # 简化：实际由运行时确定
            street=street,
            action_history=action_hash,
        )

        # 获取当前策略
        strategy = self.get_strategy(info_set, action_names)

        # 计算每个行动的反事实值
        action_values: Dict[str, float] = {}
        node_value = 0.0

        for action_name, amount in actions:
            # 计算执行此行动后的状态
            new_stacks = list(stacks)
            new_bets = list(current_bets)
            new_pot = pot
            new_reach = list(reach_probs)
            new_action_history = action_history + [f"{player}:{action_name}"]
            new_raise_rounds = raise_rounds

            if action_name == "fold":
                # 对手赢得底池中fold玩家已投入的部分
                action_values[action_name] = -current_bets[player]

            elif action_name == "check":
                action_values[action_name] = self._cfr_continue(
                    player, street, pot, stacks, current_bets,
                    reach_probs, action_history, raise_rounds, action_name,
                    depth=depth + 1,
                )

            elif action_name == "call":
                call_cost = min(to_call, stacks[player])
                new_stacks[player] -= call_cost
                new_bets[player] += call_cost
                new_pot += call_cost

                action_values[action_name] = self._cfr_continue(
                    player, street, new_pot, new_stacks, new_bets,
                    reach_probs, new_action_history, raise_rounds, action_name,
                    depth=depth + 1,
                )

            elif action_name.startswith("raise") or action_name == "allin":
                raise_cost = min(amount - current_bets[player], stacks[player])
                new_stacks[player] -= raise_cost
                new_bets[player] = amount
                new_pot += raise_cost
                new_raise_rounds += 1

                action_values[action_name] = self._cfr_continue(
                    player, street, new_pot, new_stacks, new_bets,
                    reach_probs, new_action_history, new_raise_rounds, action_name,
                    depth=depth + 1,
                )

            # 加权贡献
            node_value += strategy.get(action_name, 0.0) * action_values.get(action_name, 0.0)

        # 计算反事实遗憾
        regrets = {}
        for action_name in action_names:
            regrets[action_name] = action_values.get(action_name, 0.0) - node_value

        # 更新遗憾值
        opp_reach = reach_probs[opp]
        self._update_regrets(info_set, action_names, regrets, opp_reach)

        # 更新reach_probs用于策略累积
        for action_name in action_names:
            new_reach = list(reach_probs)
            new_reach[player] *= strategy.get(action_name, 0.0)
            self.strategy_sum[self._info_set_key(info_set)][action_name] += (
                strategy.get(action_name, 0.0) * reach_probs[player]
            )

        return node_value

    def _cfr_continue(
        self, player: int, street: str, pot: int, stacks: List[int],
        current_bets: List[int], reach_probs: List[float],
        action_history: List[str], raise_rounds: int,
        last_action: str, depth: int = 0,
    ) -> float:
        """判断下一步是继续遍历还是终止"""
        opp = 1 - player

        # 判断是否街道结束
        street_over = False
        if last_action == "call":
            street_over = True
        elif last_action == "check":
            # check后如果对手也check了
            if len(action_history) >= 2:
                prev_action = action_history[-2].split(":")[1] if len(action_history) >= 2 else ""
                if prev_action == "check":
                    street_over = True
            # preflop: BB check结束
            if street == "preflop" and len(action_history) >= 3:
                street_over = True

        if street_over:
            next_streets = ["preflop", "flop", "turn", "river"]
            idx = next_streets.index(street) if street in next_streets else 0

            if street == "river":
                # 摊牌：utility由牌力决定，训练时用随机采样
                # 简化：返回0（实际由EquityCalculator在真实使用时填充）
                return 0.0
            else:
                next_street = next_streets[idx + 1]
                return self._cfr_traverse(
                    player=opp,
                    street=next_street,
                    pot=pot,
                    stacks=stacks,
                    current_bets=[0, 0],
                    reach_probs=reach_probs,
                    action_history=action_history,
                    raise_rounds=0,
                    depth=depth + 1,
                )
        else:
            return self._cfr_traverse(
                player=opp,
                street=street,
                pot=pot,
                stacks=stacks,
                current_bets=current_bets,
                reach_probs=reach_probs,
                action_history=action_history,
                raise_rounds=raise_rounds,
                depth=depth + 1,
            )


# ── CFR+ ──────────────────────────────────────────────

class CFRPlus(VanillaCFR):
    """
    CFR+ (Tammelin 2015)

    核心改进：
    1. 负遗憾直接清零（regret matching+）
    2. 策略使用即时策略而非平均策略
    3. 收敛速度大幅提升

    用于解决Heads-up Limit Hold'em (Bowling 2015)
    """

    def _update_regrets(self, info_set: InfoSet, actions: List[str],
                        regrets: Dict[str, float], reach_prob: float) -> None:
        """CFR+ 更新：负遗憾清零"""
        key = self._info_set_key(info_set)
        strategy = self.get_strategy(info_set, actions)

        for action in actions:
            # CFR+ 核心：负遗憾清零
            old_regret = self.regret_sum[key][action]
            new_regret = old_regret + regrets.get(action, 0.0) * reach_prob
            self.regret_sum[key][action] = max(0.0, new_regret)  # 清零

            self.strategy_sum[key][action] += strategy.get(action, 0.0) * reach_prob


# ── MCCFR (Monte Carlo CFR) ────────────────────────────

class MCCFR(CFRBase):
    """
    蒙特卡洛CFR (Lanctot 2009)

    核心改进：不遍历整棵博弈树，而是采样部分路径
    适合NLHE等大博弈（完整遍历不可行）

    两种采样策略：
    - External Sampling: 采样对手+机会节点的行动，遍历自己的所有行动
    - Outcome Sampling: 采样所有人的行动

    本实现使用 External Sampling（收敛更稳定）
    """

    MAX_DEPTH = 15

    def __init__(self, *args, sampling_strategy: str = "external", **kwargs):
        super().__init__(*args, **kwargs)
        self.sampling_strategy = sampling_strategy

    def train(self, iterations: int) -> Dict[str, float]:
        logger.info(f"MCCFR ({self.sampling_strategy}) 开始训练，迭代次数: {iterations}")

        for i in range(iterations):
            self.iteration += 1

            for traversing_player in range(2):
                self._external_sampling_traverse(
                    traversing_player=traversing_player,
                    current_player=0,  # SB先行动
                    street="preflop",
                    pot=self.small_blind + self.big_blind,
                    stacks=[self.starting_stack - self.small_blind,
                            self.starting_stack - self.big_blind],
                    current_bets=[self.small_blind, self.big_blind],
                    action_history=[],
                    raise_rounds=0,
                    depth=0,
                )

            if (i + 1) % max(1, iterations // 10) == 0:
                strategy_size = len(self.strategy_sum)
                logger.info(f"  迭代 {i+1}/{iterations}, 策略表大小: {strategy_size}")

        strategy_size = len(self.strategy_sum)
        logger.info(f"MCCFR 训练完成，迭代: {self.iteration}, 策略表大小: {strategy_size}")

        return {
            "iteration": self.iteration,
            "strategy_size": strategy_size,
        }

    def _external_sampling_traverse(
        self,
        traversing_player: int,
        current_player: int,
        street: str,
        pot: int,
        stacks: List[int],
        current_bets: List[int],
        action_history: List[str],
        raise_rounds: int,
        depth: int = 0,
    ) -> float:
        """
        External Sampling: 采样对手行动，遍历自己所有行动

        Args:
            traversing_player: 被遍历的玩家(更新遗憾值)
            current_player: 当前行动的玩家
        """
        # 深度限制
        if depth >= self.MAX_DEPTH:
            return 0.0

        opp = 1 - current_player
        to_call = max(0, current_bets[opp] - current_bets[current_player])

        actions = self.action_abs.get_abstract_actions(
            pot=pot, to_call=to_call, min_raise=self.big_blind * 2,
            stack=stacks[current_player], big_blind=self.big_blind,
        )
        action_names = [a[0] for a in actions]

        action_hash = compute_action_history_hash(action_history)
        info_set = InfoSet(player=current_player, card_bucket=0, street=street, action_history=action_hash)
        strategy = self.get_strategy(info_set, action_names)

        if current_player == traversing_player:
            # traversing player: 遍历所有行动
            action_values: Dict[str, float] = {}
            node_value = 0.0

            for action_name, amount in actions:
                new_stacks = list(stacks)
                new_bets = list(current_bets)
                new_pot = pot

                if action_name == "fold":
                    action_values[action_name] = -current_bets[current_player]
                elif action_name == "call":
                    call_cost = min(to_call, stacks[current_player])
                    new_stacks[current_player] -= call_cost
                    new_bets[current_player] += call_cost
                    new_pot += call_cost
                    action_values[action_name] = self._continue_mc(
                        traversing_player, current_player, street, new_pot, new_stacks, new_bets,
                        action_history + [f"{current_player}:{action_name}"], raise_rounds, action_name,
                        depth=depth + 1,
                    )
                elif action_name == "check":
                    action_values[action_name] = self._continue_mc(
                        traversing_player, current_player, street, pot, stacks, current_bets,
                        action_history + [f"{current_player}:{action_name}"], raise_rounds, action_name,
                        depth=depth + 1,
                    )
                elif action_name.startswith("raise") or action_name == "allin":
                    raise_cost = min(amount - current_bets[current_player], stacks[current_player])
                    new_stacks[current_player] -= raise_cost
                    new_bets[current_player] = amount
                    new_pot += raise_cost
                    action_values[action_name] = self._continue_mc(
                        traversing_player, current_player, street, new_pot, new_stacks, new_bets,
                        action_history + [f"{current_player}:{action_name}"], raise_rounds + 1, action_name,
                        depth=depth + 1,
                    )

                node_value += strategy.get(action_name, 0.0) * action_values.get(action_name, 0.0)

            # 更新遗憾值
            regrets = {a: action_values.get(a, 0.0) - node_value for a in action_names}
            self._update_regrets(info_set, action_names, regrets, 1.0)

            return node_value

        else:
            # 采样对手行动
            r = random.random()
            cum_prob = 0.0
            chosen_action = action_names[0]
            chosen_amount = actions[0][1]

            for (action_name, amount), prob in zip(actions, [strategy.get(a, 0.0) for a in action_names]):
                cum_prob += prob
                if r <= cum_prob:
                    chosen_action = action_name
                    chosen_amount = amount
                    break

            # 执行采样的行动
            new_stacks = list(stacks)
            new_bets = list(current_bets)
            new_pot = pot

            if chosen_action == "fold":
                return pot - current_bets[current_player]  # 对手弃牌，我们赢
            elif chosen_action == "call":
                call_cost = min(to_call, stacks[current_player])
                new_stacks[current_player] -= call_cost
                new_bets[current_player] += call_cost
                new_pot += call_cost
            elif chosen_action.startswith("raise") or chosen_action == "allin":
                raise_cost = min(chosen_amount - current_bets[current_player], stacks[current_player])
                new_stacks[current_player] -= raise_cost
                new_bets[current_player] = chosen_amount
                new_pot += raise_cost

            return self._continue_mc(
                traversing_player, current_player, street, new_pot, new_stacks, new_bets,
                action_history + [f"{current_player}:{chosen_action}"],
                raise_rounds + (1 if chosen_action.startswith("raise") else 0),
                chosen_action,
                depth=depth + 1,
            )

    def _outcome_sampling_traverse(
        self,
        traversing_player: int,
        current_player: int,
        street: str,
        pot: int,
        stacks: List[int],
        current_bets: List[int],
        reach_probs: List[float],
        action_history: List[str],
        raise_rounds: int,
        sample_prob: float,
        depth: int = 0,
    ) -> float:
        """
        Outcome Sampling: 采样所有人的行动

        每次只遍历一条路径，用采样概率加权更新
        """
        # 简化：委托给External Sampling
        return self._external_sampling_traverse(
            traversing_player, current_player, street, pot, stacks,
            current_bets, action_history, raise_rounds, depth,
        )

    def _continue_mc(self, traversing_player: int, current_player: int,
                     street: str, pot: int, stacks: List[int],
                     current_bets: List[int], action_history: List[str],
                     raise_rounds: int, last_action: str, depth: int = 0) -> float:
        """MCCFR中的继续遍历逻辑"""
        opp = 1 - current_player
        street_over = (last_action == "call")
        if last_action == "check" and len(action_history) >= 2:
            prev = action_history[-2].split(":")[1] if len(action_history) >= 2 else ""
            if prev == "check":
                street_over = True
        # preflop: BB check结束
        if last_action == "check" and street == "preflop" and len(action_history) >= 3:
            street_over = True

        if street_over:
            if street == "river":
                return 0.0  # 摊牌由牌力决定
            next_street = {"preflop": "flop", "flop": "turn", "turn": "river"}.get(street, "river")
            return self._external_sampling_traverse(
                traversing_player=traversing_player,
                current_player=opp,
                street=next_street, pot=pot, stacks=stacks,
                current_bets=[0, 0], action_history=action_history, raise_rounds=0,
                depth=depth + 1,
            )
        else:
            return self._external_sampling_traverse(
                traversing_player=traversing_player,
                current_player=opp,
                street=street, pot=pot, stacks=stacks,
                current_bets=current_bets, action_history=action_history, raise_rounds=raise_rounds,
                depth=depth + 1,
            )
