"""锦标赛单桌管理

TournamentTable 包装 GameEngine，提供：
- 座位管理（sit/remove）
- 一手牌完整流程（含边池结算）
- 淘汰检测
- ante 支持
"""

import logging
from typing import List, Optional, Dict, Tuple

from treys import Card
from .game import GameEngine, PlayerState, Street, ActionType
from .side_pot import calculate_side_pots, distribute_pots, SidePot
from .blind_schedule import BlindLevel
from .agent import ArenaAgent

arena_logger = logging.getLogger("arena")


class TournamentTable:
    """锦标赛桌"""

    def __init__(self, table_id: int, max_seats: int = 9):
        self.table_id = table_id
        self.max_seats = max_seats
        # seats[i] = PlayerState or None
        self.seats: List[Optional[PlayerState]] = [None] * max_seats
        self.agents: Dict[int, ArenaAgent] = {}  # seat_id -> agent
        self._hand_count = 0

    @property
    def active_players(self) -> List[PlayerState]:
        """还有筹码的玩家"""
        return [p for p in self.seats if p is not None and p.stack > 0]

    @property
    def player_count(self) -> int:
        return len(self.active_players)

    def sit_player(self, player: PlayerState, agent: ArenaAgent) -> int:
        """安排玩家入座，返回 seat_id。如果满座返回 -1。"""
        for i in range(self.max_seats):
            if self.seats[i] is None:
                # 更新 seat_id 为桌内座位号
                player.seat_id = i
                self.seats[i] = player
                self.agents[i] = agent
                return i
        return -1

    def remove_player(self, seat_id: int) -> Optional[PlayerState]:
        """移除玩家，返回被移除的 PlayerState"""
        if seat_id < 0 or seat_id >= self.max_seats:
            return None
        player = self.seats[seat_id]
        self.seats[seat_id] = None
        self.agents.pop(seat_id, None)
        return player

    async def play_hand(self, blind_level: BlindLevel) -> List[Tuple[str, int]]:
        """
        打一手完整牌局。

        参数:
            blind_level: 当前盲注级别

        返回:
            [(player_id, amount), ...] 被淘汰的玩家及其最终筹码（0）
        """
        active = self.active_players
        if len(active) < 2:
            return []

        self._hand_count += 1

        # 构建本手牌参与的玩家列表（stack > 0）
        hand_players = [p for p in self.seats if p is not None and p.stack > 0]
        num_players = len(hand_players)

        if num_players < 2:
            return []

        # 构建 GameEngine 需要的 players_info
        players_info = [{'name': p.name, 'stack': p.stack} for p in hand_players]

        # 构建 seat_id -> engine_idx 映射
        seat_to_idx: Dict[int, int] = {}
        idx_to_seat: Dict[int, int] = {}
        for i, p in enumerate(hand_players):
            seat_to_idx[p.seat_id] = i
            idx_to_seat[i] = p.seat_id

        engine = GameEngine(players_info, blind_level.sb, blind_level.bb)

        # 庄家轮换
        dealer_idx = (self._hand_count - 1) % num_players
        engine.reset_hand(dealer_idx, self._hand_count)
        engine.deal_hole_cards()

        # 发盲注（含 ante）
        current_idx = engine.post_blinds(ante=blind_level.ante)

        # 翻牌前
        await self._betting_loop(engine, current_idx, hand_players, seat_to_idx, idx_to_seat)

        # 后续街道
        while engine.current_street < Street.RIVER and self._count_active(engine) > 1:
            engine.next_street()
            first_actor = (engine.dealer_idx + 1) % num_players
            await self._betting_loop(engine, first_actor, hand_players, seat_to_idx, idx_to_seat)

        # 摊牌记录
        if self._count_active(engine) > 1:
            curr_street = engine.current_street
            street_name = curr_street.name if isinstance(curr_street, Street) else str(curr_street)
            for p in engine.players:
                if p.is_active:
                    engine_seat = idx_to_seat.get(engine.players.index(p), -1)
                    if engine_seat >= 0 and engine_seat in self.agents:
                        for agent in self.agents.values():
                            agent.observe_showdown(p.seat_id, p.hole_cards, street_name)

        # 结算：使用边池模块
        winners = self._settle_with_side_pots(engine, idx_to_seat)
        for seat_id, amount in winners:
            if seat_id < len(engine.players):
                engine.players[seat_id].stack += amount

        # 记录人类玩家的手牌结果
        winner_seats = {ws for ws, _ in winners}
        for i, ep in enumerate(engine.players):
            real_seat = idx_to_seat[i]
            agent = self.agents.get(real_seat)
            if agent and agent.is_human:
                is_winner = i in winner_seats
                win_amount = next((a for s, a in winners if s == i), 0)
                arena_logger.info(
                    f"🎮 CLI 手牌结果: {'赢' if is_winner else '输'} "
                    f"win={win_amount} pot={engine.pot} "
                    f"board={' '.join(Card.int_to_str(c) for c in engine.community_cards)}"
                )

        # 将 engine 的筹码变化同步回 hand_players -> seats
        busted: List[Tuple[str, int]] = []
        for i, ep in enumerate(engine.players):
            real_seat = idx_to_seat[i]
            if real_seat < self.max_seats and self.seats[real_seat] is not None:
                self.seats[real_seat].stack = ep.stack
                if ep.stack == 0:
                    player_id = self.seats[real_seat].player_id
                    busted.append((player_id, 0))

        return busted

    async def _betting_loop(self, engine: GameEngine, start_idx: int,
                      hand_players: List[PlayerState],
                      seat_to_idx: Dict[int, int],
                      idx_to_seat: Dict[int, int]):
        """投注循环"""
        num_players = len(hand_players)

        if self._count_can_act(engine) <= 1:
            return

        acted = [False] * num_players
        current_idx = start_idx

        max_iterations = num_players * 20  # 防止死循环
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # 检查是否所有人都已行动
            all_done = all(
                not engine.players[i].is_active or engine.players[i].is_all_in or acted[i]
                for i in range(num_players)
            )
            if all_done:
                p = engine.players[current_idx]
                if not p.is_active or p.is_all_in or p.bet_this_street == engine.current_bet:
                    break

            p = engine.players[current_idx]

            if p.is_active and not p.is_all_in:
                real_seat = idx_to_seat.get(current_idx, -1)
                agent = self.agents.get(real_seat)

                if agent:
                    action, amount = await agent.get_action(engine)
                    engine.execute_action(current_idx, action, amount)
                else:
                    # 无 agent 默认弃牌
                    engine.execute_action(current_idx, ActionType.FOLD)

                acted[current_idx] = True

                if action in [ActionType.RAISE, ActionType.ALL_IN]:
                    for i in range(num_players):
                        if i != current_idx:
                            acted[i] = False

            if self._count_active(engine) <= 1:
                break

            current_idx = (current_idx + 1) % num_players

    def _count_active(self, engine: GameEngine) -> int:
        return sum(1 for p in engine.players if p.is_active)

    def _count_can_act(self, engine: GameEngine) -> int:
        return sum(1 for p in engine.players if p.is_active and not p.is_all_in)

    def _settle_with_side_pots(self, engine: GameEngine,
                                idx_to_seat: Dict[int, int]) -> List[Tuple[int, int]]:
        """使用边池模块结算"""
        active_players = [p for p in engine.players if p.is_active]

        # 只剩一人：直接拿走底池
        if len(active_players) == 1:
            winner = active_players[0]
            return [(winner.seat_id, engine.pot)]

        # 多人摊牌：计算边池
        investments = [(p.seat_id, p.total_investment) for p in engine.players
                       if p.is_active or p.is_all_in]

        pots = calculate_side_pots(investments)
        hole_cards_map = {p.seat_id: p.hole_cards for p in engine.players if p.is_active}

        return distribute_pots(
            pots, hole_cards_map, engine.community_cards, engine.evaluator
        )
