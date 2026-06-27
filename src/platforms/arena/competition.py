import logging
import os
import time
from pathlib import Path
from typing import List, Dict, Optional
from src.platforms.arena.game import GameEngine, Street, ActionType
from src.platforms.arena.agent import ArenaAgent
from src.strategies.strategies.range import RangeStrategy
from src.utils.logger import arena_logger


def setup_arena_logging(log_file: str = "logs/arena.log"):
    """配置竞技场日志：重定向至全局日志系统"""
    from src.utils.logger import setup_logger
    setup_logger("arena", os.path.basename(log_file))
    arena_logger.info(f"竞技场日志已定向至: {log_file}")


class Competition:
    """对抗赛运行器：管理多场对局并统计结果"""
    def __init__(self, strategy_names: List[str], initial_stack: int = 1000,
                 small_blind: int = 5, big_blind: int = 10,
                 player_stacks: Optional[List[int]] = None):
        self.initial_stack = initial_stack
        self.sb = small_blind
        self.bb = big_blind

        # 1. 初始化策略管理器
        from src.strategies.strategy_manager import StrategyManager
        self._strategy_mgr = StrategyManager(thinking_timeout=2.0)

        # 2. 初始化玩家与策略
        players_info = []
        self.agents: List[ArenaAgent] = []

        for i, sname in enumerate(strategy_names):
            strategy = self._create_strategy(sname)
            agent = ArenaAgent(seat_id=i, strategy=strategy)
            self.agents.append(agent)
            stack = player_stacks[i] if player_stacks and i < len(player_stacks) else initial_stack
            players_info.append({'name': agent.name, 'stack': stack})
            
        # 2. 初始化核心引擎
        self.engine = GameEngine(players_info, small_blind, big_blind)
        
        # 3. 统计数据
        self.stats = {
            i: {
                'name': agent.name,
                'profit': 0,
                'total_rebuys': 0,
                'locked_profit': 0,
                'hands_played': 0,
                'vpip_count': 0,
                'pfr_count': 0,
                'wins': 0,
                # 风格量化指标
                'bet_count': 0,
                'raise_count': 0,
                'call_count': 0,
                'three_bet_count': 0,
                'three_bet_opps': 0,
                'saw_flop_count': 0,
                'saw_showdown_count': 0,
                'won_at_showdown': 0,
                'total_pot_won': 0,
            } for i, agent in enumerate(self.agents)
        }
        
    def _create_strategy(self, strategy_type: str):
        """通过 StrategyManager 创建策略，失败时回退到 RangeStrategy"""
        strategy = self._strategy_mgr.create_strategy(
            table_id=f"arena_{strategy_type}",
            strategy_type=strategy_type,
        )
        if strategy is not None:
            return strategy
        arena_logger.warning(f"未知策略 '{strategy_type}'，回退到 range")
        return RangeStrategy()

    async def run(self, num_hands: int):
        """运行 N 手牌"""
        arena_logger.info(f"=== 竞技场对抗赛开始 (总计 {num_hands} 手) ===")
        start_time = time.time()

        for h in range(num_hands):
            dealer_idx = h % len(self.agents)
            await self._run_single_hand(dealer_idx, h + 1)

        duration = time.time() - start_time
        self._print_summary(num_hands, duration)

    async def _run_single_hand(self, dealer_idx: int, hand_idx: int):
        # 0. 筹码管理策略
        initial_bb_stack = self.initial_stack
        min_bb_stack = 10 * self.bb
        max_bb_stack = 400 * self.bb

        for i, p in enumerate(self.engine.players):
            if p.stack < min_bb_stack:
                rebuy_amount = initial_bb_stack - p.stack
                arena_logger.info(f"玩家 {p.name} 筹码告急 ({p.stack})，Rebuy +{rebuy_amount}")
                self.stats[i]['total_rebuys'] += rebuy_amount
                p.stack = initial_bb_stack
            elif p.stack > max_bb_stack:
                lock_amount = p.stack - max_bb_stack
                arena_logger.info(f"玩家 {p.name} 筹码过厚 ({p.stack})，落袋为安 +{lock_amount}")
                self.stats[i]['locked_profit'] += lock_amount
                p.stack = max_bb_stack

        last_vpip_counts = {i: self.stats[i]['vpip_count'] for i in range(len(self.agents))}
        last_pfr_counts = {i: self.stats[i]['pfr_count'] for i in range(len(self.agents))}

        self.engine.reset_hand(dealer_idx, hand_idx)
        self.engine.deal_hole_cards()
        
        # 统计参加次数
        for i, p in enumerate(self.engine.players):
            if p.is_active:
                self.stats[i]['hands_played'] += 1
        
        # 盲注层
        current_idx = self.engine.post_blinds()
        
        # 翻牌前环节 (Pre-flop)
        await self._betting_loop(current_idx)

        # 后续环节
        saw_flop = False
        while self.engine.current_street < Street.RIVER and self._count_active() > 1:
            self.engine.next_street()
            if not saw_flop and self.engine.current_street >= Street.FLOP:
                saw_flop = True
                for i, p in enumerate(self.engine.players):
                    if p.is_active:
                        self.stats[i]['saw_flop_count'] += 1
            first_actor = (self.engine.dealer_idx + 1) % len(self.agents)
            await self._betting_loop(first_actor)
            
        # 结算前记录摊牌
        is_showdown = self._count_active() > 1
        if is_showdown:
            curr_street = self.engine.current_street
            street_name = curr_street.name if isinstance(curr_street, Street) else str(curr_street)
            for i, p in enumerate(self.engine.players):
                if p.is_active:
                    self.stats[i]['saw_showdown_count'] += 1
                    for agent in self.agents:
                        agent.observe_showdown(p.seat_id, p.hole_cards, street_name)

        # 结算
        winners = self.engine.get_winners()
        winner_seats = set()
        for seat_id, amount in winners:
            self.engine.players[seat_id].stack += amount
            self.stats[seat_id]['wins'] += 1
            self.stats[seat_id]['total_pot_won'] += amount
            winner_seats.add(seat_id)

        # 摊牌赢率追踪
        if is_showdown:
            for seat_id in winner_seats:
                self.stats[seat_id]['won_at_showdown'] += 1
            
        # 每一手结束后，向所有 Agent 分发本手统计
        for i in range(len(self.agents)):
            is_vpip = self.stats[i]['vpip_count'] > last_vpip_counts[i]
            is_pfr = self.stats[i]['pfr_count'] > last_pfr_counts[i]
            for agent in self.agents:
                agent.update_global_stats(i, is_vpip, is_pfr)

        # 更新盈亏统计
        for i, p in enumerate(self.engine.players):
            self.stats[i]['profit'] = (p.stack + self.stats[i]['locked_profit']) - (self.initial_stack + self.stats[i]['total_rebuys'])

    async def _betting_loop(self, start_idx: int):
        """单回合投注循环"""
        num_players = len(self.agents)
        current_idx = start_idx
        
        if self._count_can_act() <= 1:
            return

        acted = [False] * num_players
        
        while True:
            p = self.engine.players[current_idx]
            
            if all(not self.engine.players[i].is_active or self.engine.players[i].is_all_in or acted[i] for i in range(num_players)):
                if not p.is_active or p.is_all_in or p.bet_this_street == self.engine.current_bet:
                    break
            
            if p.is_active and not p.is_all_in:
                agent = self.agents[current_idx]
                action, amount = await agent.get_action(self.engine)

                # 翻前 3-bet 机会追踪：面对加注（current_bet > BB）时有行动机会
                if self.engine.current_street == Street.PREFLOP and self.engine.current_bet > self.bb:
                    self.stats[current_idx]['three_bet_opps'] += 1

                self._record_behavior_stats(current_idx, action)
                
                self.engine.execute_action(current_idx, action, amount)
                acted[current_idx] = True
                
                for other_agent in self.agents:
                    other_agent.observe_action(current_idx, action, amount, self.engine.pot)
                
                if action in [ActionType.RAISE, ActionType.ALL_IN]:
                    for i in range(num_players):
                        if i != current_idx: acted[i] = False
            
            if self._count_can_act() <= 1 and self.engine.current_bet == p.bet_this_street:
                 pass

            current_idx = (current_idx + 1) % num_players
            
            if self._count_active() <= 1:
                break

    def _count_active(self):
        return sum(1 for p in self.engine.players if p.is_active)
        
    def _count_can_act(self):
        return sum(1 for p in self.engine.players if p.is_active and not p.is_all_in)

    def _record_behavior_stats(self, idx: int, action: ActionType):
        # 全街追踪 bet/raise/call
        # Arena ActionType 没有 BET，翻后 RAISE 等同于 bet
        if action == ActionType.RAISE:
            if self.engine.current_street == Street.PREFLOP:
                self.stats[idx]['raise_count'] += 1
            else:
                self.stats[idx]['bet_count'] += 1
        elif action == ActionType.CALL:
            self.stats[idx]['call_count'] += 1

        # 翻前专属统计
        if self.engine.current_street == Street.PREFLOP:
            if action in [ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN]:
                self.stats[idx]['vpip_count'] += 1
            if action in [ActionType.RAISE, ActionType.ALL_IN]:
                self.stats[idx]['pfr_count'] += 1
            # 3-bet 追踪：翻前已有加注(current_bet > BB)时再加注
            if action in [ActionType.RAISE, ActionType.ALL_IN] and self.engine.current_bet > self.bb:
                self.stats[idx]['three_bet_count'] += 1

    def _print_summary(self, num_hands: int, duration: float):
        print("\n" + "="*100)
        print(f"🃏 竞技场完赛报告 (对抗手数: {num_hands}, 耗时: {duration:.1f}s, 盲注: {self.sb}/{self.bb})")
        print("-" * 100)
        header = f"{'玩家':<18} | {'BB/100':>7} | {'AF':>5} | {'3B%':>5} | {'VPIP%':>6} | {'PFR%':>6} | {'WTSD%':>6} | {'W$SD%':>6} | {'AvgPot':>7} | {'胜场':>4}"
        print(header)
        print("-" * 100)

        for i in range(len(self.agents)):
            s = self.stats[i]
            hp = s['hands_played'] or 1

            # BB/100
            bb_per_100 = (s['profit'] / self.bb) / hp * 100 if hp > 0 else 0

            # AF = (bet + raise) / call
            total_aggressive = s['bet_count'] + s['raise_count']
            af = total_aggressive / s['call_count'] if s['call_count'] > 0 else float(total_aggressive)

            # 3B%
            three_bet_pct = (s['three_bet_count'] / s['three_bet_opps'] * 100) if s['three_bet_opps'] > 0 else 0

            # VPIP / PFR
            vpip = (s['vpip_count'] / hp * 100) if hp > 0 else 0
            pfr = (s['pfr_count'] / hp * 100) if hp > 0 else 0

            # WTSD% = saw_showdown / saw_flop
            wtsd = (s['saw_showdown_count'] / s['saw_flop_count'] * 100) if s['saw_flop_count'] > 0 else 0

            # W$SD% = won_at_showdown / saw_showdown
            wsdp = (s['won_at_showdown'] / s['saw_showdown_count'] * 100) if s['saw_showdown_count'] > 0 else 0

            # Avg Pot = total_pot_won / wins
            avg_pot = (s['total_pot_won'] / s['wins']) if s['wins'] > 0 else 0

            print(f"{s['name']:<18} | {bb_per_100:>+7.1f} | {af:>5.1f} | {three_bet_pct:>5.1f} | {vpip:>6.1f} | {pfr:>6.1f} | {wtsd:>6.1f} | {wsdp:>6.1f} | {avg_pot:>7.0f} | {s['wins']:>4}")

        # 补充 Rebuy/Locked 信息
        for i in range(len(self.agents)):
            s = self.stats[i]
            tags = []
            if s['total_rebuys'] > 0:
                tags.append(f"Rebuy: {s['total_rebuys']}")
            if s['locked_profit'] > 0:
                tags.append(f"Locked: {s['locked_profit']}")
            if tags:
                print(f"  {s['name']}: {', '.join(tags)}")

        print("="*100 + "\n")