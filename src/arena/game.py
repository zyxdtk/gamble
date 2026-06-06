import enum
import random
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from treys import Card, Deck, Evaluator

# 设置竞技场日志
arena_logger = logging.getLogger("arena")
arena_logger.setLevel(logging.INFO)
if not arena_logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter('[ARENA] %(message)s')
    ch.setFormatter(formatter)
    arena_logger.addHandler(ch)

class Street(enum.IntEnum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3
    SHOWDOWN = 4

class ActionType(enum.Enum):
    FOLD = "FOLD"
    CHECK = "CHECK"
    CALL = "CALL"
    RAISE = "RAISE"
    ALL_IN = "ALL_IN"

@dataclass
class PlayerState:
    seat_id: int
    name: str
    stack: int
    hole_cards: List[int] = field(default_factory=list)
    is_active: bool = True
    is_all_in: bool = False
    bet_this_street: int = 0
    total_investment: int = 0  # 本手牌总投入
    
    def __repr__(self):
        return f"Player(Seat {self.seat_id}, {self.name}, Stack: {self.stack})"

class GameEngine:
    """德州扑克核心规则引擎"""
    def __init__(self, players_info: List[Dict], small_blind: int = 1, big_blind: int = 2):
        self.players: List[PlayerState] = [
            PlayerState(seat_id=i, name=p['name'], stack=p['stack'])
            for i, p in enumerate(players_info)
        ]
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.evaluator = Evaluator()
        
        self.deck = Deck()
        self.community_cards: List[int] = []
        self.pot = 0
        self.side_pots = [] # 复杂边池逻辑后续增强
        self.dealer_idx = 0
        self.current_street = Street.PREFLOP
        self.last_raiser_idx = -1
        self.current_bet = 0
        self.min_raise = big_blind
        
    def reset_hand(self, dealer_idx: int, hand_idx: int = 1):
        """重置一手牌"""
        self.deck = Deck()
        self.community_cards = []
        self.pot = 0
        self.dealer_idx = dealer_idx
        self.current_street = Street.PREFLOP
        
        for p in self.players:
            p.hole_cards = []
            p.is_active = p.stack > 0
            p.is_all_in = False
            p.bet_this_street = 0
            p.total_investment = 0
            
        arena_logger.info(f"--- 第 {hand_idx} 局对局开始 (庄家: 座位 {dealer_idx}) ---")
        
    def deal_hole_cards(self):
        for p in self.players:
            if p.is_active:
                p.hole_cards = self.deck.draw(2)
                arena_logger.info(f"玩家 {p.name} (座:{p.seat_id}) 手牌: {[Card.int_to_str(c) for c in p.hole_cards]}")
                
    def post_blinds(self) -> List[int]:
        """缴纳盲注，返回当前需要行动的玩家索引"""
        num_players = len(self.players)
        sb_idx = (self.dealer_idx + 1) % num_players
        bb_idx = (self.dealer_idx + 2) % num_players
        
        # 处理只有两人的情况（Heads-up）
        if num_players == 2:
            sb_idx = self.dealer_idx
            bb_idx = (self.dealer_idx + 1) % num_players
            
        self._bet(sb_idx, self.small_blind)
        self._bet(bb_idx, self.big_blind)
        
        self.current_bet = self.big_blind
        self.last_raiser_idx = bb_idx
        self.min_raise = self.big_blind
        
        arena_logger.info(f"玩家 {self.players[sb_idx].name} 缴纳小盲 {self.small_blind}, 玩家 {self.players[bb_idx].name} 缴纳大盲 {self.big_blind}")
        
        return (bb_idx + 1) % num_players

    def _bet(self, player_idx: int, amount: int):
        p = self.players[player_idx]
        actual_amount = min(amount, p.stack)
        p.stack -= actual_amount
        p.bet_this_street += actual_amount
        p.total_investment += actual_amount
        self.pot += actual_amount
        if p.stack == 0:
            p.is_all_in = True
            arena_logger.info(f"玩家 {p.name} ALL-IN!")

    def execute_action(self, player_idx: int, action_type: ActionType, amount: int = 0) -> bool:
        """执行玩家动作。amount 只在 RAISE 时有效。"""
        p = self.players[player_idx]
        to_call = self.current_bet - p.bet_this_street
        
        if action_type == ActionType.FOLD:
            p.is_active = False
            arena_logger.info(f"玩家 {p.name} 弃牌 (FOLD)")
        elif action_type == ActionType.CHECK:
            if to_call > 0:
                arena_logger.warning(f"由于有下注 {to_call}，玩家 {p.name} 无法过牌，强制弃牌")
                p.is_active = False
            else:
                arena_logger.info(f"玩家 {p.name} 过牌 (CHECK)")
        elif action_type == ActionType.CALL:
            self._bet(player_idx, to_call)
            arena_logger.info(f"玩家 {p.name} 跟注 (CALL) {to_call}")
        elif action_type == ActionType.RAISE:
            # 这里的 amount 应该是总注额
            actual_total_bet = amount
            raise_amount = actual_total_bet - p.bet_this_street
            
            min_required = p.bet_this_street + to_call + self.min_raise
            if actual_total_bet < min_required and p.stack > raise_amount:
                arena_logger.warning(f"加注额 {amount} 过小，最小应为 {min_required}")
                # 兼容处理：自动修正为最小加注
                actual_total_bet = min_required
                raise_amount = actual_total_bet - p.bet_this_street
                
            self.min_raise = actual_total_bet - self.current_bet
            self.current_bet = actual_total_bet
            self.last_raiser_idx = player_idx
            self._bet(player_idx, raise_amount)
            arena_logger.info(f"玩家 {p.name} 加注 (RAISE) 至 {actual_total_bet}")
        elif action_type == ActionType.ALL_IN:
            all_in_amount = p.stack + p.bet_this_street
            if all_in_amount > self.current_bet:
                self.min_raise = max(self.min_raise, all_in_amount - self.current_bet)
                self.current_bet = all_in_amount
                self.last_raiser_idx = player_idx
            self._bet(player_idx, p.stack)
            arena_logger.info(f"玩家 {p.name} 全下 (ALL-IN) {all_in_amount}")
            
        return True

    def next_street(self):
        """进入下一个回合"""
        self.current_street = Street(self.current_street + 1)
        self.current_bet = 0
        self.last_raiser_idx = -1
        self.min_raise = self.big_blind
        for p in self.players:
            p.bet_this_street = 0
            
        if self.current_street == Street.FLOP:
            self.community_cards = self.deck.draw(3)
            arena_logger.info(f"--- 翻牌 (FLOP): {[Card.int_to_str(c) for c in self.community_cards]} | 底池: {self.pot} ---")
        elif self.current_street == Street.TURN:
            self.community_cards.append(self.deck.draw(1))
            arena_logger.info(f"--- 转牌 (TURN): {[Card.int_to_str(c) for c in self.community_cards]} | 底池: {self.pot} ---")
        elif self.current_street == Street.RIVER:
            self.community_cards.append(self.deck.draw(1))
            arena_logger.info(f"--- 河牌 (RIVER): {[Card.int_to_str(c) for c in self.community_cards]} | 底池: {self.pot} ---")
            
    def get_winners(self) -> List[Tuple[int, int]]:
        """计算最终赢家和分配金额。简化版：暂不处理复杂的边池情况。"""
        active_players = [p for p in self.players if p.is_active]
        if len(active_players) == 1:
            winner = active_players[0]
            arena_logger.info(f"所有其他玩家已弃牌，玩家 {winner.name} 赢得底池 {self.pot}")
            return [(winner.seat_id, self.pot)]
            
        # 比牌逻辑
        scores = []
        for p in active_players:
            score = self.evaluator.evaluate(self.community_cards, p.hole_cards)
            rank_class = self.evaluator.get_rank_class(score)
            class_str = self.evaluator.class_to_string(rank_class)
            arena_logger.info(f"玩家 {p.name} 摊牌: {[Card.int_to_str(c) for c in p.hole_cards]} -> {class_str}")
            scores.append((score, p))
            
        scores.sort(key=lambda x: x[0])
        best_score = scores[0][0]
        winners = [x[1] for x in scores if x[0] == best_score]
        
        # 分摊底池
        win_amount = self.pot // len(winners)
        results = []
        for w in winners:
            arena_logger.info(f"玩家 {w.name} 赢得底池 {win_amount}")
            results.append((w.seat_id, win_amount))
            
        return results
