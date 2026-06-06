"""边池计算与分配模块

处理 all-in 场景下的主池/边池拆分及奖金分配。
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict
from treys import Evaluator, Card


@dataclass
class SidePot:
    """边池"""
    amount: int                # 该边池的总金额
    eligible_seats: List[int]  # 有资格竞争该边池的座位号


def calculate_side_pots(players_investments: List[Tuple[int, int]]) -> List[SidePot]:
    """
    根据各玩家的 total_investment 计算主池和边池。

    参数:
        players_investments: [(seat_id, total_investment), ...]
            只包含已参与本手牌的玩家（is_active 或 is_all_in）

    返回: List[SidePot]，从主池到边池排序

    算法:
        1. 按 total_investment 升序排列
        2. 从最小投资开始，依次计算每个层级
        3. 每个层级的金额 = 该层投资额 × 有资格人数 - 前面已分配的金额
    """
    if not players_investments:
        return []

    # 按投资额排序
    sorted_invest = sorted(players_investments, key=lambda x: x[1])

    # 提取唯一投资额（升序）
    unique_levels = sorted(set(inv for _, inv in sorted_invest))

    pots: List[SidePot] = []
    prev_level = 0

    for level in unique_levels:
        if level <= prev_level:
            continue

        # 该层有资格的玩家：投资额 >= level 的所有人
        eligible = [seat for seat, inv in sorted_invest if inv >= level]

        # 该层贡献金额 = (level - prev_level) * 有资格人数
        # 但需排除投资额不足 level 的人数（已在 eligible 中过滤）
        contributing_count = len([seat for seat, inv in sorted_invest if inv >= level])
        pot_amount = (level - prev_level) * contributing_count

        if pot_amount > 0:
            pots.append(SidePot(
                amount=pot_amount,
                eligible_seats=eligible,
            ))

        prev_level = level

    return pots


def evaluate_hands(
    eligible_seats: List[int],
    hole_cards_map: Dict[int, List[int]],
    community_cards: List[int],
    evaluator: Evaluator,
) -> List[List[int]]:
    """
    评估有资格玩家的手牌，返回赢家组。

    返回: [[seat_id, ...], ...] 每个内层列表是同分赢家
    """
    if not eligible_seats:
        return []

    scored: List[Tuple[int, int]] = []
    for seat_id in eligible_seats:
        cards = hole_cards_map.get(seat_id, [])
        if len(cards) < 2:
            continue
        score = evaluator.evaluate(community_cards, cards)
        scored.append((score, seat_id))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0])
    best_score = scored[0][0]
    winners = [seat_id for score, seat_id in scored if score == best_score]

    # 返回分组：赢家的座位列表
    return [winners]


def distribute_pots(
    pots: List[SidePot],
    hole_cards_map: Dict[int, List[int]],
    community_cards: List[int],
    evaluator: Evaluator,
    active_only_seats: List[int] | None = None,
) -> List[Tuple[int, int]]:
    """
    按边池分别分配奖金。

    参数:
        pots: calculate_side_pots 的结果
        hole_cards_map: {seat_id: [card_int, card_int]}
        community_cards: 公共牌
        evaluator: treys Evaluator
        active_only_seats: 如果只剩余一人未弃牌，直接给底池；否则 None

    返回: [(seat_id, amount), ...] 各玩家赢得的金额
    """
    # 特殊情况：只有一人还在场（其他全弃牌），直接拿走所有池
    if active_only_seats and len(active_only_seats) == 1:
        total = sum(pot.amount for pot in pots)
        return [(active_only_seats[0], total)]

    distribution: Dict[int, int] = {}

    for pot in pots:
        # 评估该边池内有资格的玩家
        winner_groups = evaluate_hands(
            pot.eligible_seats, hole_cards_map, community_cards, evaluator
        )

        if not winner_groups:
            continue

        # 平分给同分赢家
        winners = winner_groups[0]
        share = pot.amount // len(winners)
        remainder = pot.amount % len(winners)

        for i, seat_id in enumerate(winners):
            amount = share + (1 if i < remainder else 0)
            distribution[seat_id] = distribution.get(seat_id, 0) + amount

    return list(distribution.items())
