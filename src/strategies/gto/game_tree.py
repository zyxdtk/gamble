"""
博弈树：CFR遍历的核心数据结构

设计要点：
1. 树节点存储：信息集 → 可选行动 → 子节点
2. 支持两种构建方式：
   - 完整构建（Leduc等小博弈）
   - 延迟展开（NLHE，按需展开子树）
3. 终端节点：计算效用值(utility)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from .abstraction import InfoSet, ActionAbstraction, CardAbstraction, compute_action_history_hash


# ── 节点类型 ──────────────────────────────────────────

class NodeType(Enum):
    CHANCE = auto()      # 机会节点（发牌）
    DECISION = auto()    # 决策节点（玩家行动）
    TERMINAL = auto()    # 终端节点（结算）


@dataclass
class TreeNode:
    """博弈树节点"""
    node_type: NodeType
    info_set: Optional[InfoSet] = None
    # 决策节点: action_name → 子节点
    children: Dict[str, 'TreeNode'] = field(default_factory=dict)
    # 终端节点: 各玩家的效用值
    utility: Optional[List[float]] = None
    # 机会节点: 各结果的概率
    chance_outcomes: Dict[str, float] = field(default_factory=dict)
    # 树深度
    depth: int = 0
    # 父节点引用（弱引用避免循环）
    parent: Optional['TreeNode'] = None

    def is_leaf(self) -> bool:
        return self.node_type == NodeType.TERMINAL

    def add_child(self, action: str, child: 'TreeNode') -> None:
        child.parent = self
        child.depth = self.depth + 1
        self.children[action] = child

    def get_actions(self) -> List[str]:
        """获取所有可选行动"""
        return list(self.children.keys())


# ── 博弈树构建器 ──────────────────────────────────────

class GameTree:
    """
    德州扑克简化博弈树

    针对CFR训练做了关键简化：
    1. 限定2人HU (Heads-Up)
    2. 动作抽象：固定几个加注尺度
    3. 牌面抽象：equity bucketing
    4. 限定每条街的最大加注轮数(防止树爆炸)

    使用方式：
    - build(): 构建完整博弈树（用于小博弈验证）
    - build_subtree(): 按需构建子树（用于NLHE的endgame solving）
    """

    # 每条街最大加注轮数（防止树爆炸）
    MAX_RAISE_ROUNDS_PER_STREET = 3
    # 最大递归深度（硬限制防止无限展开）
    MAX_DEPTH = 15

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
        self.root: Optional[TreeNode] = None

        # 统计
        self.node_count = 0
        self.terminal_count = 0

    def build(self) -> TreeNode:
        """
        构建完整博弈树

        注意：NLHE完整博弈树极其庞大(~10^160)，
        仅在抽象后才能构建。实际训练用MCCFR采样。
        """
        self.root = TreeNode(node_type=NodeType.DECISION, depth=0)
        self.node_count = 1

        # 从preflop开始构建
        self._build_recursive(
            node=self.root,
            street="preflop",
            pot=self.small_blind + self.big_blind,
            stacks=[self.starting_stack - self.small_blind,
                    self.starting_stack - self.big_blind],
            current_bets=[self.small_blind, self.big_blind],
            player=0,  # SB先行动(HU)
            action_history=[],
            raise_rounds=0,
        )

        return self.root

    def _build_recursive(
        self,
        node: TreeNode,
        street: str,
        pot: int,
        stacks: List[int],
        current_bets: List[int],
        player: int,
        action_history: List[str],
        raise_rounds: int,
    ) -> None:
        """递归构建博弈树"""

        # 深度限制：防止无限展开
        if node.depth >= self.MAX_DEPTH:
            node.node_type = NodeType.TERMINAL
            node.utility = [0.0, 0.0]
            self.terminal_count += 1
            return

        opp = 1 - player
        to_call = current_bets[opp] - current_bets[player]

        # 获取抽象化后的行动列表
        actions = self.action_abs.get_abstract_actions(
            pot=pot,
            to_call=to_call,
            min_raise=self.big_blind * 2,
            stack=stacks[player],
            big_blind=self.big_blind,
        )

        # 构建信息集
        action_hash = compute_action_history_hash(action_history)
        # 注意：实际bucket由运行时确定，这里用0占位
        info_set = InfoSet(
            player=player,
            card_bucket=0,  # 运行时填充
            street=street,
            action_history=action_hash,
        )
        node.info_set = info_set

        for action_name, amount in actions:
            child = TreeNode(
                node_type=NodeType.DECISION,
                depth=node.depth + 1,
            )
            self.node_count += 1

            # 计算执行此行动后的新状态
            new_stacks = list(stacks)
            new_bets = list(current_bets)
            new_pot = pot
            new_raise_rounds = raise_rounds
            new_action_history = action_history + [f"{player}:{action_name}"]

            if action_name == "fold":
                # 终端节点：对手赢
                child.node_type = NodeType.TERMINAL
                # 效用：fold玩家失去已投入，对手赢得底池
                child.utility = [-current_bets[player], pot - current_bets[opp]]
                self.terminal_count += 1

            elif action_name in ("check", "call"):
                if action_name == "call":
                    new_stacks[player] -= to_call
                    new_bets[player] += to_call
                    new_pot += to_call

                # 判断是否这条街结束
                if self._is_street_over(new_action_history, street, player):
                    if street == "river":
                        # 到摊牌
                        child.node_type = NodeType.TERMINAL
                        # utility在运行时由牌力决定，这里存0占位
                        child.utility = [0.0, 0.0]  # 运行时填充
                        self.terminal_count += 1
                    else:
                        # 进入下一条街
                        next_street = self._next_street(street)
                        child.node_type = NodeType.DECISION
                        self._build_recursive(
                            node=child,
                            street=next_street,
                            pot=new_pot,
                            stacks=new_stacks,
                            current_bets=[0, 0],  # 新街道重置
                            player=self._first_to_act(next_street),
                            action_history=new_action_history,
                            raise_rounds=0,
                        )
                else:
                    # 继续当前街道
                    child.node_type = NodeType.DECISION
                    self._build_recursive(
                        node=child,
                        street=street,
                        pot=new_pot,
                        stacks=new_stacks,
                        current_bets=new_bets,
                        player=opp,
                        action_history=new_action_history,
                        raise_rounds=raise_rounds,
                    )

            elif action_name.startswith("raise") or action_name == "allin":
                raise_total = amount
                raise_cost = raise_total - current_bets[player]
                raise_cost = min(raise_cost, stacks[player])

                new_stacks[player] -= raise_cost
                new_bets[player] = raise_total
                new_pot += raise_cost
                new_raise_rounds += 1

                # 判断是否超过最大加注轮数
                if new_raise_rounds >= self.MAX_RAISE_ROUNDS_PER_STREET:
                    # 限制：后续只能call或fold
                    child.node_type = NodeType.DECISION
                    self._build_recursive(
                        node=child,
                        street=street,
                        pot=new_pot,
                        stacks=new_stacks,
                        current_bets=new_bets,
                        player=opp,
                        action_history=new_action_history,
                        raise_rounds=new_raise_rounds,
                    )
                else:
                    child.node_type = NodeType.DECISION
                    self._build_recursive(
                        node=child,
                        street=street,
                        pot=new_pot,
                        stacks=new_stacks,
                        current_bets=new_bets,
                        player=opp,
                        action_history=new_action_history,
                        raise_rounds=new_raise_rounds,
                    )

            node.add_child(action_name, child)

    def build_subtree(
        self,
        street: str,
        pot: int,
        stacks: List[int],
        current_bets: List[int],
        player: int,
    ) -> TreeNode:
        """
        按需构建子树（Endgame Solving）

        从指定状态开始构建博弈树，用于实时求解
        """
        root = TreeNode(node_type=NodeType.DECISION, depth=0)
        self._build_recursive(
            node=root,
            street=street,
            pot=pot,
            stacks=stacks,
            current_bets=current_bets,
            player=player,
            action_history=[],
            raise_rounds=0,
        )
        return root

    def _is_street_over(self, action_history: List[str], street: str,
                        last_player: int) -> bool:
        """判断当前街道的betting round是否结束

        HU简化规则:
        1. call → 街道结束（无论preflop还是postflop）
        2. check后对手也check → 街道结束
        3. preflop: BB check (open=SB raise, BB call后不加注)
        """
        if not action_history:
            return False

        last_action_name = action_history[-1].split(":")[1]

        # call 总是结束本街
        if last_action_name == "call":
            return True

        # check: 需要连续两人都check
        if last_action_name == "check":
            # 至少2个行动且前一个也是check
            if len(action_history) >= 2:
                prev_action_name = action_history[-2].split(":")[1]
                if prev_action_name == "check":
                    return True
            # preflop特殊情况: BB面对SB的call后check (HU中BB是最后一个行动)
            if street == "preflop" and len(action_history) >= 3:
                return True

        return False

    def _next_street(self, street: str) -> str:
        """获取下一条街"""
        order = ["preflop", "flop", "turn", "river"]
        idx = order.index(street) if street in order else 0
        return order[min(idx + 1, len(order) - 1)]

    def _first_to_act(self, street: str) -> int:
        """获取某条街第一个行动的玩家"""
        # preflop: SB先行动(HU), 其他: SB(位置0)先行动
        # 简化：非preflop时player 0先行动
        if street == "preflop":
            return 0  # HU: SB先行动
        return 0  # 简化

    def count_nodes(self) -> Dict[str, int]:
        """统计博弈树节点数"""
        result = {"decision": 0, "terminal": 0, "total": 0}

        def _count(node: TreeNode):
            result["total"] += 1
            if node.node_type == NodeType.TERMINAL:
                result["terminal"] += 1
            else:
                result["decision"] += 1
            for child in node.children.values():
                _count(child)

        if self.root:
            _count(self.root)
        return result
