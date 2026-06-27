import numpy as np
import torch
import torch.nn as nn
import os
from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType
from src.strategies.game_state import GameState
from src.strategies.utils import normalize_hand_string
from src.strategies.utils.tactical_calc import TacticalCalculator
from ...utils.logger import brain_logger


class QNet(nn.Module):
    def __init__(self, num_actions=5, state_shape=(92,), mlp_layers=[512, 512]):
        super(QNet, self).__init__()
        self.num_actions = num_actions
        self.state_shape = state_shape
        self.mlp_layers = mlp_layers

        input_dim = np.prod(self.state_shape)
        layer_dims = [input_dim] + self.mlp_layers

        fc = [nn.Flatten()]
        fc.append(nn.BatchNorm1d(layer_dims[0]))

        for i in range(len(layer_dims)-1):
            fc.append(nn.Linear(layer_dims[i], layer_dims[i+1], bias=True))
            fc.append(nn.Tanh())

        fc.append(nn.Linear(layer_dims[-1], self.num_actions, bias=True))
        self.fc_layers = nn.Sequential(*fc)

    def forward(self, s):
        return self.fc_layers(s)


class NeuralStrategy(Strategy):
    """
    神经模型策略 (Neural Model Strategy)
    使用 RLCard 训练的 DQN 模型进行决策推理。
    支持扩展 92 维观测向量（v2）和旧版 54 维（v1 legacy）。
    """
    strategy_name = "neural"

    # 新旧模型维度
    STATE_SHAPE_V2 = 92
    STATE_SHAPE_V1 = 54

    def __init__(self, model_path: str = "data/models/nlh_dqn.pth", thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_loaded = False
        self.model_version = 2  # 默认 v2（92 维）

        if not model_path.startswith('/'):
             model_path = os.path.join(os.getcwd(), model_path)

        # 先尝试加载 v2 模型，失败则回退 v1
        if os.path.exists(model_path):
            self._load_model(model_path)
        else:
            brain_logger.warning(f"未找到模型文件 {model_path}，将回退到启发式决策。")

        self.suit_map = {'s': 0, 'h': 1, 'd': 2, 'c': 3}
        self.rank_map = {'A': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6, '8': 7, '9': 8, 'T': 9, 'J': 10, 'Q': 11, 'K': 12}

    def _load_model(self, path: str):
        """加载模型权重，自动检测 v1/v2 维度"""
        try:
            state_dict = torch.load(path, map_location=self.device)
            # 检测维度：通过第一个线性层的输入特征判断
            first_key = list(state_dict.keys())[0]
            first_weight = state_dict[first_key]
            if first_weight.shape[-1] == self.STATE_SHAPE_V1:
                self.model_version = 1
                self.model = QNet(num_actions=5, state_shape=(self.STATE_SHAPE_V1,), mlp_layers=[512, 512]).to(self.device)
            else:
                self.model_version = 2
                self.model = QNet(num_actions=5, state_shape=(self.STATE_SHAPE_V2,), mlp_layers=[512, 512]).to(self.device)

            self.model.load_state_dict(state_dict)
            self.model.eval()
            self.model_loaded = True
            brain_logger.info(f"深度模型加载成功 (v{self.model_version}, {self.model.state_shape}): {path}")
        except Exception as e:
            brain_logger.error(f"模型加载失败 (架构不匹配或路径错误): {e}")

    def make_decision(self, state: GameState) -> ActionPlan:
        """实施基于神经网络的推理决策"""
        if not self.model_loaded:
            plan = self._get_balanced_plan(state)
            plan.reasoning = f"[Neural-Fallback] {plan.reasoning}"
            return plan

        # 预计算战术上下文（用于扩展特征）
        self._compute_tactical_context(state)

        obs_vec = self._state_to_obs(state)
        obs_tensor = torch.from_numpy(obs_vec).unsqueeze(0).to(self.device)

        with torch.no_grad():
            q_values = self.model(obs_tensor)
            legal_actions = self._get_legal_actions_indices(state)

            masked_q = q_values.clone()
            for act in range(5):
                if act not in legal_actions:
                    masked_q[0, act] = -1e9

            action_idx = torch.argmax(masked_q).item()

        return self._map_action_to_plan(action_idx, state)

    def _state_to_obs(self, state: GameState) -> np.ndarray:
        """将 GameState 转换为观测向量。v2=92维, v1=54维(legacy)"""
        if self.model_version == 1:
            return self._state_to_obs_v1(state)
        return self._state_to_obs_v2(state)

    def _state_to_obs_v1(self, state: GameState) -> np.ndarray:
        """旧版 54 维向量（向后兼容）"""
        obs = np.zeros(54, dtype=np.float32)
        all_cards = (state.hole_cards or []) + (state.community_cards or [])
        for card in all_cards:
            if len(card) >= 2:
                rank_char = card[0]
                suit_char = card[1]
                if rank_char in self.rank_map and suit_char in self.suit_map:
                    idx = self.suit_map[suit_char] * 13 + self.rank_map[rank_char]
                    if idx < 52:
                        obs[idx] = 1.0

        pot = state.pot if state.pot > 0 else 2
        my_chips_in = state.players.get(state.my_seat_id, type('obj', (), {'bet': 0})()).bet

        opp_chips_in = 0
        for seat, p in state.players.items():
            if seat != state.my_seat_id and p.is_active:
                opp_chips_in = max(opp_chips_in, p.bet)

        bb = max(state.big_blind, 1)
        obs[52] = float(my_chips_in) / bb
        obs[53] = float(opp_chips_in) / bb
        return obs

    def _state_to_obs_v2(self, state: GameState) -> np.ndarray:
        """扩展 92 维观测向量"""
        obs = np.zeros(92, dtype=np.float32)
        tc = state.tactical_context

        # 特征组1: 牌面 one-hot (52 维, obs[0:52])
        all_cards = (state.hole_cards or []) + (state.community_cards or [])
        for card in all_cards:
            if len(card) >= 2:
                rank_char = card[0]
                suit_char = card[1]
                if rank_char in self.rank_map and suit_char in self.suit_map:
                    idx = self.suit_map[suit_char] * 13 + self.rank_map[rank_char]
                    if idx < 52:
                        obs[idx] = 1.0

        bb = max(state.big_blind, 1)
        pot = max(state.pot, 1)

        # 特征组2: 我的已下注/BB (1 维, obs[52])
        my_bet = state.players.get(state.my_seat_id, type('obj', (), {'bet': 0})()).bet
        obs[52] = float(my_bet) / bb

        # 特征组3: 对手最大下注/BB (1 维, obs[53])
        opp_max_bet = 0
        for seat, p in state.players.items():
            if seat != state.my_seat_id and p.is_active:
                opp_max_bet = max(opp_max_bet, p.bet)
        obs[53] = float(opp_max_bet) / bb

        # 特征组4: 底池大小 (1 维, obs[54]) — log 归一化
        obs[54] = np.log1p(float(pot)) / 10.0

        # 特征组5: to_call/pot (1 维, obs[55])
        obs[55] = float(state.to_call) / pot if pot > 0 else 0.0

        # 特征组6: 底池赔率 (1 维, obs[56])
        obs[56] = tc.pot_odds if tc else 0.0

        # 特征组7: SPR (1 维, obs[57]) — clip [0, 20]
        spr = tc.spr if tc else 20.0
        obs[57] = min(max(spr, 0.0), 20.0) / 20.0

        # 特征组8: 位置 one-hot (6 维, obs[58:64])
        # EP, MP, LP, BTN, SB, BB
        pos_map = {"EP": 0, "UTG": 0, "MP": 1, "LP": 2, "BTN": 3, "SB": 4, "BB": 5}
        pos_code = tc.position_code if tc else "ALL"
        pos_idx = pos_map.get(pos_code, -1)
        if pos_idx >= 0:
            obs[58 + pos_idx] = 1.0

        # 特征组9: 街道 one-hot (4 维, obs[64:68])
        # preflop, flop, turn, river
        street = tc.street if tc else "preflop"
        street_map = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
        street_idx = street_map.get(street, 0)
        obs[64 + street_idx] = 1.0

        # 特征组10: 对手数 (1 维, obs[68]) — /9 归一化
        num_opp = tc.num_opponents if tc else 1
        obs[68] = float(num_opp) / 9.0

        # 特征组11: 能否加注/跟注 (2 维, obs[69:71])
        obs[69] = 1.0 if state.total_chips > state.to_call + state.min_raise else 0.0  # can_raise
        obs[70] = 1.0 if state.total_chips > state.to_call else 0.0  # can_call

        # 特征组12: 对手均 VPIP (1 维, obs[71])
        obs[71] = tc.avg_vpip if tc else 0.3

        # 特征组13: 牌面湿润度 (1 维, obs[72])
        wetness = tc.board_texture.get("wetness", 0.0) if tc and tc.board_texture else 0.0
        obs[72] = wetness

        # 特征组14: 预估胜率 (1 维, obs[73])
        obs[73] = tc.equity if tc else 0.0

        # 特征组15: 翻前牌力等级 one-hot (4 维, obs[74:78])
        # tier 1=超强, 2=强, 3=中, 0=弱
        hand_str = tc.hand_str if tc else "XX"
        tier = self.range_mgr.get_hand_tier(hand_str)
        obs[74 + min(tier, 3)] = 1.0

        # 特征组16: 保留 (14 维, obs[78:92]) — 零
        # 已预分配零

        return obs

    def _get_legal_actions_indices(self, state: GameState) -> list:
        legal = [0, 1]
        if state.total_chips > state.to_call:
            legal.extend([2, 3, 4])
        return legal

    def _map_action_to_plan(self, idx: int, state: GameState) -> ActionPlan:
        to_call = state.to_call
        pot = state.pot
        my_bet = state.players.get(state.my_seat_id, type('obj', (), {'bet': 0})()).bet

        if idx == 0:
            return ActionPlan(ActionType.FOLD if to_call > 0 else ActionType.CHECK, reasoning="Neural: FOLD/CHECK")
        if idx == 1:
            return ActionPlan(ActionType.CALL if to_call > 0 else ActionType.CHECK, reasoning="Neural: CALL/CHECK")
        if idx == 2:
            amount = my_bet + int(pot * 0.5)
            return ActionPlan(ActionType.RAISE, primary_amount=amount, bet_size_hint="half_pot", reasoning="Neural: RAISE 0.5 POT")
        if idx == 3:
            amount = my_bet + int(pot)
            return ActionPlan(ActionType.RAISE, primary_amount=amount, bet_size_hint="pot", reasoning="Neural: RAISE POT")
        if idx == 4:
            plan = ActionPlan(ActionType.RAISE, primary_amount=state.total_chips, bet_size_hint="max", reasoning="Neural: ALL-IN")
        else:
            plan = self._get_balanced_plan(state)

        plan.strategy_name = self.strategy_name
        plan.my_equity = self._last_equity
        return plan
