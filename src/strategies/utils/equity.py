from __future__ import annotations
import random

try:
    from treys import Card, Evaluator, Deck
except ImportError:
    Card = None
    Evaluator = None
    Deck = None


class EquityCalculator:
    _instance = None
    evaluator = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.evaluator = Evaluator() if Evaluator else None
        return cls._instance
    
    def calculate_equity(self, hole_cards: list[str], community_cards: list[str], 
                         num_opponents: int = 1, iterations: int = 500) -> float:
        if not self.evaluator or not Card:
            return self._estimate_preflop_equity(hole_cards)
        
        try:
            hero_cards = [self._to_treys(c) for c in hole_cards]
            board_cards = [self._to_treys(c) for c in community_cards]
            
            if None in hero_cards or None in board_cards:
                return 0.0
            
            wins = 0
            ties = 0
            
            deck = Deck()
            known_cards = hero_cards + board_cards
            for card in known_cards:
                if card in deck.cards:
                    deck.cards.remove(card)
            
            for _ in range(iterations):
                current_deck = list(deck.cards)
                random.shuffle(current_deck)
                
                villain_hands = []
                for _ in range(num_opponents):
                    if len(current_deck) < 2:
                        break
                    villain_cards = [current_deck.pop(), current_deck.pop()]
                    villain_hands.append(villain_cards)
                
                cards_needed = 5 - len(board_cards)
                if len(current_deck) < cards_needed:
                    continue
                
                sim_board = board_cards + [current_deck.pop() for _ in range(cards_needed)]
                
                hero_score = self.evaluator.evaluate(hero_cards, sim_board)
                villain_scores = [self.evaluator.evaluate(vh, sim_board) for vh in villain_hands]
                best_villain_score = min(villain_scores) if villain_scores else float('inf')
                
                if hero_score < best_villain_score:
                    wins += 1
                elif hero_score == best_villain_score:
                    ties += 1
            
            return (wins + (ties / 2)) / iterations
        
        except Exception:
            return self._estimate_preflop_equity(hole_cards)
    
    def calculate_ev(self, equity: float, pot: int, to_call: int,
                     raise_amount: int = 0, fold_equity: float = 0.0) -> dict:
        """计算三种主要行动的期望值（EV）。
        
        Args:
            equity:       我方胜率（蒙特卡洛模拟结果）
            pot:          当前底池
            to_call:      需要跟注的金额
            raise_amount: 计划加注的额外筹码
            fold_equity:  对手因我们加注而弃牌的估计概率（0~1）
        
        Returns:
            dict: fold_ev, call_ev, raise_ev, best_action, best_ev
        """
        # 1. FOLD EV：永远是 0（放弃底池，不失去更多）
        fold_ev = 0.0
        
        # 2. CALL EV = equity × 赢得总底池 - 跟注费用
        call_ev = 0.0
        if to_call > 0:
            total_pot_if_call = pot + to_call
            call_ev = equity * total_pot_if_call - to_call
        else:
            # 无需跟注（check 场景），EV = equity × 当前底池
            call_ev = equity * pot
        
        # 3. RAISE EV = 弃牌权益 × 当前底池赢得 + 跟注后的胜率 EV
        raise_ev = 0.0
        if raise_amount > 0:
            total_pot_if_raise = pot + to_call + raise_amount + raise_amount  # 双方各加
            showdown_ev = equity * total_pot_if_raise - (to_call + raise_amount)
            immediate_win = pot  # 对手弃牌时立刻赢得当前底池
            raise_ev = fold_equity * immediate_win + (1 - fold_equity) * showdown_ev
        
        # 4. 推荐最优行动
        evs = {"FOLD": fold_ev, "CALL": call_ev}
        if raise_amount > 0:
            evs["RAISE"] = raise_ev
        
        best_action = max(evs, key=lambda k: evs[k])
        best_ev = evs[best_action]
        
        return {
            "fold_ev": round(fold_ev, 2),
            "call_ev": round(call_ev, 2),
            "raise_ev": round(raise_ev, 2) if raise_amount > 0 else None,
            "best_action": best_action,
            "best_ev": round(best_ev, 2),
        }

    def estimate_fold_equity(self, opp_vpip: float, opp_pfr: float, street: str) -> float:
        """粗估对手在面对我们加注时的弃牌概率（Fold Equity）。
        
        VPIP 越高（越松）→ 弃牌率越高
        街道越靠后（Turn/River）→ 对手已经投入更多，弃牌率越低
        """
        if opp_vpip <= 0:
            return 0.25  # 下调默认期望：低级别对局对手更倾向于跟注而非弃牌
        base_fold_rate = min(0.60, max(0.10, (opp_vpip - 10) / 80))
        street_factor = {"preflop": 1.0, "flop": 0.85, "turn": 0.70, "river": 0.50}
        factor = street_factor.get(street.lower(), 0.75)
        return round(base_fold_rate * factor, 2)

    def find_optimal_raise_size(
        self, equity: float, pot: int, to_call: int,
        min_raise: int, stack: int,
        base_fold_equity: float = 0.40
    ) -> dict:
        """通过 EV 最大化找到最优加注尺度。
        
        加注越大：
         - 赢得底池越多（若摊牌）
         - 对手弃牌概率越高（弃牌权益增加）
         - 自身成本越高
        
        Args:
            equity:           我方摊牌胜率
            pot:              当前底池
            to_call:          需要跟注金额
            min_raise:        场上最小加注额
            stack:            我方剩余筹码（上限 = all-in）
            base_fold_equity: 基础弃牌率（来自 estimate_fold_equity）
        
        Returns:
            dict:
              optimal_amount:  EV 最大的加注金额
              optimal_ev:      对应的 EV
              bet_size_hint:   建议快捷按钮 (min/half_pot/pot/max)
              ev_by_size:      各档位的 EV 对比
        """
        if pot <= 0 or min_raise <= 0 or stack <= 0:
            return {
                "optimal_amount": min_raise or pot,
                "optimal_ev": 0.0,
                "bet_size_hint": "half_pot",
                "ev_by_size": {}
            }
        
        # 构造候选档位：MIN / ½POT / POT / 2×POT / ALL-IN
        candidates = {
            "min":      max(min_raise, 1),
            "half_pot": max(min_raise, int(pot * 0.5)),
            "pot":      max(min_raise, pot),
            "max":      stack,
        }
        # 过滤超出 stack 的
        candidates = {k: min(v, stack) for k, v in candidates.items()}
        # 去重
        seen = set()
        unique_candidates = {}
        for k, v in candidates.items():
            if v not in seen:
                seen.add(v)
                unique_candidates[k] = v
        
        def raise_ev_at(r: int) -> float:
            """计算加注 r 时的 EV。随加注增大，弃牌率也动态增加。"""
            if r <= 0:
                return 0.0
            # 下注尺度比（bet / pot），用于动态调整弃牌率
            bet_ratio = r / pot if pot > 0 else 1.0
            # 加注越大，对手弃牌概率越高，但有上限（75%）
            dynamic_fold_eq = min(0.75, base_fold_equity * (1 + bet_ratio * 0.5))
            
            total_pot = pot + to_call + r + r  # 双方各投
            showdown_ev = equity * total_pot - (to_call + r)
            immediate_win = pot
            ev = dynamic_fold_eq * immediate_win + (1 - dynamic_fold_eq) * showdown_ev
            return round(ev, 2)
        
        ev_by_size = {k: raise_ev_at(v) for k, v in unique_candidates.items()}
        
        # 找到 EV 最大的档位
        best_hint = max(ev_by_size, key=lambda k: ev_by_size[k])
        best_amount = unique_candidates[best_hint]
        best_ev = ev_by_size[best_hint]
        
        return {
            "optimal_amount": best_amount,
            "optimal_ev": best_ev,
            "bet_size_hint": best_hint,
            "ev_by_size": ev_by_size,
        }

    def get_hand_strength(self, hole_cards: list[str], community_cards: list[str]) -> dict:
        """识别当前的牌型。"""
        if not self.evaluator or not Card or not community_cards:
            return {"combination": "none", "points": 0, "draws": self.detect_draws(hole_cards, community_cards)}
            
        try:
            hero_cards = [self._to_treys(c) for c in hole_cards]
            board_cards = [self._to_treys(c) for c in community_cards]
            
            if None in hero_cards or None in board_cards:
                return {"combination": "none", "points": 0, "draws": self.detect_draws(hole_cards, community_cards)}
            
            # 使用 treys evaluator 获取得分和牌型类
            score = self.evaluator.evaluate(hero_cards, board_cards)
            hand_class = self.evaluator.get_rank_class(score)
            class_str = self.evaluator.class_to_string(hand_class).lower().replace(" ", "_")
            
            # 增加听牌识别
            draws = self.detect_draws(hole_cards, community_cards)
            
            return {
                "combination": class_str,
                "points": 8000 - score, # score 越小牌越强，转换成点数
                "draws": draws
            }
        except Exception:
            return {"combination": "none", "points": 0, "draws": self.detect_draws(hole_cards, community_cards)}

    def detect_draws(self, hole_cards: list[str], community_cards: list[str]) -> dict:
        """
        探测当前的听牌情况（Flush Draw, OESD, Gutshot）
        """
        result = {
            "flush_draw": False,
            "flush_outs": 0,
            "oesd": False,
            "gutshot": False,
            "straight_outs": 0
        }
        
        if not hole_cards or len(hole_cards) < 2:
            return result
            
        all_cards = hole_cards + community_cards
        if len(all_cards) < 4: # 至少 4 张才能听牌
            return result

        # 1. 探测 Flush Draw (4 张同色)
        suits = [c[1].lower() for c in all_cards]
        for s in set(suits):
            if suits.count(s) == 4:
                result["flush_draw"] = True
                result["flush_outs"] = 9
                break

        # 2. 探测顺子听牌 (使用点数去重排序)
        rank_map = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"T":10,"J":11,"Q":12,"K":13,"A":14}
        ranks = sorted(list(set([rank_map.get(c[0].upper(), 0) for c in all_cards])))
        
        if 14 in ranks: # 处理 A
            ranks = [1] + ranks # 把 A 当作 1 处理一次
            ranks = sorted(list(set(ranks)))

        # 滑动窗口查找 4 张连续或跨度为 4 的组合
        for i in range(len(ranks)):
            for j in range(i + 3, len(ranks)):
                sub = ranks[i:j+1]
                if len(sub) < 4: continue
                
                # 取 4 张
                for k in range(len(sub) - 3):
                    window = sub[k:k+4]
                    span = window[-1] - window[0]
                    
                    if span == 3: # OESD (如果是两头)
                        # 检查两头是否都能补 (1-14 溢出除外)
                        result["oesd"] = True
                        result["straight_outs"] = max(result["straight_outs"], 8)
                    elif span == 4: # Gutshot
                        result["gutshot"] = True
                        result["straight_outs"] = max(result["straight_outs"], 4)
                        
        return result
            
    def _to_treys(self, card_str: str):
        if len(card_str) == 2:
            return Card.new(f"{card_str[0].upper()}{card_str[1].lower()}")
        return None
    
    def _estimate_preflop_equity(self, hole_cards: list[str]) -> float:
        if not hole_cards or len(hole_cards) < 2:
            return 0.0
        
        hand_str = self._normalize_hand(hole_cards)
        
        if hand_str[0] == hand_str[1]:
            rank = hand_str[0]
            if rank == 'A':
                return 0.85
            if rank == 'K':
                return 0.82
            if rank == 'Q':
                return 0.80
            if rank == 'J':
                return 0.77
            if rank == 'T':
                return 0.75
            if rank in '987':
                return 0.70
            return 0.65
        
        if 'A' in hand_str:
            if 'K' in hand_str:
                return 0.67 if 's' in hand_str else 0.65
            if 'Q' in hand_str:
                return 0.66 if 's' in hand_str else 0.64
            if 'J' in hand_str:
                return 0.65 if 's' in hand_str else 0.62
            return 0.60 if 's' in hand_str else 0.55
        
        if 'K' in hand_str:
            if 'Q' in hand_str:
                return 0.63 if 's' in hand_str else 0.60
            if 'J' in hand_str:
                return 0.60 if 's' in hand_str else 0.57
            return 0.55 if 's' in hand_str else 0.50
        
        return 0.35
    
    def _normalize_hand(self, hole_cards: list[str]) -> str:
        if not hole_cards or len(hole_cards) < 2:
            return "XX"
        
        ranks = "23456789TJQKA"
        try:
            c1, c2 = hole_cards[0], hole_cards[1]
            if not c1 or not c2 or len(c1) < 2 or len(c2) < 2:
                return "XX"
            
            r1_idx = ranks.index(c1[0].upper())
            r2_idx = ranks.index(c2[0].upper())
            
            if r1_idx < r2_idx:
                c1, c2 = c2, c1
                r1_idx, r2_idx = r2_idx, r1_idx
            
            is_suited = c1[1].lower() == c2[1].lower()
            suffix = "s" if is_suited else "o"
            
            if c1[0].upper() == c2[0].upper():
                return c1[0].upper() + c2[0].upper()
            return c1[0].upper() + c2[0].upper() + suffix
        except (ValueError, IndexError):
            return "XX"
