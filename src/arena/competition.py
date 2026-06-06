import logging
import os
import time
from pathlib import Path
from typing import List, Dict
from src.arena.game import GameEngine, Street, ActionType
from src.arena.agent import ArenaAgent
from src.strategies.strategies.balanced import BalancedStrategy
from src.strategies.strategies.exploitative import ExploitativeStrategy
from src.strategies.strategies.range import RangeStrategy
from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
from src.strategies.strategies.neural import NeuralStrategy
from src.utils.logger import arena_logger


def setup_arena_logging(log_file: str = "logs/arena.log"):
    """配置竞技场日志：重定向至全局日志系统"""
    from src.utils.logger import setup_logger
    setup_logger("arena", os.path.basename(log_file))
    arena_logger.info(f"竞技场日志已定向至: {log_file}")


class Competition:
    """对抗赛运行器：管理多场对局并统计结果"""
    def __init__(self, strategy_names: List[str], initial_stack: int = 1000, 
                 small_blind: int = 1, big_blind: int = 2):
        self.initial_stack = initial_stack
        self.sb = small_blind
        self.bb = big_blind
        
        # 1. 初始化玩家与策略
        players_info = []
        self.agents: List[ArenaAgent] = []
        
        for i, sname in enumerate(strategy_names):
            strategy = self._create_strategy(sname, 2.0)
            agent = ArenaAgent(seat_id=i, strategy=strategy)
            self.agents.append(agent)
            players_info.append({'name': agent.name, 'stack': initial_stack})
            
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
                'wins': 0
            } for i, agent in enumerate(self.agents)
        }
        
    def _create_strategy(self, strategy_type: str, timeout: float):
        strategy_type = strategy_type.lower()
        if strategy_type == "balanced" or strategy_type == "gto":
            return BalancedStrategy(thinking_timeout=timeout)
        elif strategy_type == "exploitative":
            return ExploitativeStrategy(thinking_timeout=timeout)
        elif strategy_type == "neural":
            return NeuralStrategy(thinking_timeout=timeout)
        elif strategy_type == "checkorfold":
            return CheckOrFoldStrategy()
        else:
            return RangeStrategy()

    def run(self, num_hands: int):
        """运行 N 手牌"""
        arena_logger.info(f"=== 竞技场对抗赛开始 (总计 {num_hands} 手) ===")
        start_time = time.time()
        
        for h in range(num_hands):
            dealer_idx = h % len(self.agents)
            self._run_single_hand(dealer_idx, h + 1)
            
        duration = time.time() - start_time
        self._print_summary(num_hands, duration)

    def _run_single_hand(self, dealer_idx: int, hand_idx: int):
        # 0. 筹码管理策略
        initial_bb_stack = 100 * self.bb
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
        self._betting_loop(current_idx)
        
        # 后续环节
        while self.engine.current_street < Street.RIVER and self._count_active() > 1:
            self.engine.next_street()
            first_actor = (self.engine.dealer_idx + 1) % len(self.agents)
            self._betting_loop(first_actor)
            
        # 结算前记录摊牌
        if self._count_active() > 1:
            curr_street = self.engine.current_street
            street_name = curr_street.name if isinstance(curr_street, Street) else str(curr_street)
            for p in self.engine.players:
                if p.is_active:
                    for agent in self.agents:
                        agent.observe_showdown(p.seat_id, p.hole_cards, street_name)

        # 结算
        winners = self.engine.get_winners()
        for seat_id, amount in winners:
            self.engine.players[seat_id].stack += amount
            self.stats[seat_id]['wins'] += 1
            
        # 每一手结束后，向所有 Agent 分发本手统计
        for i in range(len(self.agents)):
            is_vpip = self.stats[i]['vpip_count'] > last_vpip_counts[i]
            is_pfr = self.stats[i]['pfr_count'] > last_pfr_counts[i]
            for agent in self.agents:
                agent.update_global_stats(i, is_vpip, is_pfr)

        # 更新盈亏统计
        for i, p in enumerate(self.engine.players):
            self.stats[i]['profit'] = (p.stack + self.stats[i]['locked_profit']) - (self.initial_stack + self.stats[i]['total_rebuys'])

    def _betting_loop(self, start_idx: int):
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
                action, amount = agent.get_action(self.engine)
                
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
        if self.engine.current_street == Street.PREFLOP:
            if action in [ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN]:
                self.stats[idx]['vpip_count'] += 1
            if action in [ActionType.RAISE, ActionType.ALL_IN]:
                self.stats[idx]['pfr_count'] += 1

    def _print_summary(self, num_hands: int, duration: float):
        print("\n" + "="*60)
        print(f"🃏 竞技场完赛报告 (对抗手数: {num_hands}, 耗时: {duration:.1f}s)")
        print("-" * 60)
        print(f"{'玩家 (策略)':<25} | {'盈亏':>8} | {'VPIP%':>6} | {'PFR%':>6} | {'胜场':>4}")
        print("-" * 60)
        
        for i in range(len(self.agents)):
            s = self.stats[i]
            vpip = (s['vpip_count'] / s['hands_played'] * 100) if s['hands_played'] > 0 else 0
            pfr = (s['pfr_count'] / s['hands_played'] * 100) if s['hands_played'] > 0 else 0
            
            rebuy_tag = f" (Rebuy: {s['total_rebuys']})" if s['total_rebuys'] > 0 else ""
            lock_tag = f" (Locked: {s['locked_profit']})" if s['locked_profit'] > 0 else ""
            print(f"{s['name']:<25} | {s['profit']:>8} | {vpip:>6.1f}% | {pfr:>6.1f}% | {s['wins']:>4}{rebuy_tag}{lock_tag}")
        print("="*60 + "\n")