import numpy as np
import torch
import torch.nn as nn
import os
from src.strategies.strategy_base import Strategy
from src.strategies.action_plan import ActionPlan, ActionType
from src.strategies.game_state import GameState
from src.strategies.utils import normalize_hand_string
from ...utils.logger import brain_logger


class QNet(nn.Module):
    def __init__(self, num_actions=5, state_shape=(54,), mlp_layers=[512, 512]):
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
    """
    strategy_name = "neural"

    def __init__(self, model_path: str = "data/models/nlh_dqn.pth", thinking_timeout: float = 2.0):
        super().__init__(thinking_timeout)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = QNet(num_actions=5, state_shape=(54,), mlp_layers=[512, 512]).to(self.device)
        self.model_loaded = False
        
        if not model_path.startswith('/'):
             model_path = os.path.join(os.getcwd(), model_path)
             
        if os.path.exists(model_path):
            self._load_model(model_path)
        else:
            brain_logger.warning(f"未找到模型文件 {model_path}，将回退到启发式决策。")
            
        self.suit_map = {'S': 0, 'H': 1, 'D': 2, 'C': 3}
        self.rank_map = {'A': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6, '8': 7, '9': 8, 'T': 9, 'J': 10, 'Q': 11, 'K': 12}

    def _load_model(self, path: str):
        """加载模型权重"""
        try:
            state_dict = torch.load(path, map_location=self.device)
            self.model.load_state_dict(state_dict)
            self.model.eval()
            self.model_loaded = True
            brain_logger.info(f"深度模型加载成功并完成架构匹配: {path}")
        except Exception as e:
            brain_logger.error(f"模型加载失败 (架构不匹配或路径错误): {e}")

    def make_decision(self, state: GameState) -> ActionPlan:
        """实施基于神经网络的推理决策"""
        if not self.model_loaded:
            plan = self._get_balanced_plan(state)
            plan.reasoning = f"[Neural-Fallback] {plan.reasoning}"
            return plan

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
        """将 GameState 转换为 RLCard 标准 54 维向量"""
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
        
        obs[52] = float(my_chips_in)
        obs[53] = float(opp_chips_in)
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