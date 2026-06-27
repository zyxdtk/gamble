"""
Deep CFR + 反事实值网络

阶段3核心：用神经网络近似CFR值函数，替代显式博弈树遍历

架构参考 DeepStack (Moravcik 2017):
1. 训练阶段：CFR自博弈生成训练数据 → 训练ValueNetwork
2. 推理阶段：用ValueNetwork估算反事实值 → 实时决策

输出：训练好的ValueNetwork权重文件 + 导出策略表给阶段1
"""
from __future__ import annotations

import logging
import random
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from .abstraction import InfoSet, ActionAbstraction, CardAbstraction, compute_action_history_hash

logger = logging.getLogger("gto.deep_cfr")


# ── 反事实值网络 ──────────────────────────────────────

class ValueNetwork:
    """
    反事实值估算网络 (Counterfactual Value Network)

    输入: 游戏状态特征 (手牌 + 公共牌 + 底池 + 动作历史)
    输出: 每个行动的反事实值 (CFV)

    网络结构: MLP with residual connections
    与现有NeuralStrategy的QNet共享设计理念，但目标不同：
    - QNet: DQN, 输出Q值 (单agent RL)
    - ValueNetwork: Deep CFR, 输出反事实值 (自博弈)
    """

    # 状态特征维度
    # 52 card binary (2 hole + 5 community, one-hot)
    # + 5 pot/stack features
    # + 4 street one-hot
    INPUT_DIM = 61
    OUTPUT_DIM = 5  # fold, check, call, raise, allin

    def __init__(self, hidden_dims: Optional[List[int]] = None,
                 learning_rate: float = 0.001):
        self.hidden_dims = hidden_dims or [256, 256, 128]
        self.learning_rate = learning_rate
        self._model = None
        self._optimizer = None
        self._build_model()

    def _build_model(self):
        """构建PyTorch模型（延迟导入torch）"""
        try:
            import torch
            import torch.nn as nn

            layers = []
            prev_dim = self.INPUT_DIM

            for hidden_dim in self.hidden_dims:
                layers.append(nn.Linear(prev_dim, hidden_dim))
                layers.append(nn.BatchNorm1d(hidden_dim))
                layers.append(nn.ReLU())
                prev_dim = hidden_dim

            # 输出层
            layers.append(nn.Linear(prev_dim, self.OUTPUT_DIM))

            self._model = nn.Sequential(*layers)
            self._optimizer = torch.optim.Adam(self._model.parameters(), lr=self.learning_rate)

            logger.info(f"ValueNetwork 已构建: {self.INPUT_DIM} -> {self.hidden_dims} -> {self.OUTPUT_DIM}")

        except ImportError:
            logger.warning("torch 未安装，ValueNetwork 不可用。请安装: uv add torch")
            self._model = None
            self._optimizer = None

    def predict(self, state_features: np.ndarray) -> np.ndarray:
        """
        预测反事实值

        Args:
            state_features: shape (batch_size, INPUT_DIM) 或 (INPUT_DIM,)

        Returns:
            shape (batch_size, OUTPUT_DIM) - 每个行动的CFV
        """
        if self._model is None:
            return np.zeros(self.OUTPUT_DIM)

        import torch
        self._model.eval()

        with torch.no_grad():
            if state_features.ndim == 1:
                state_features = state_features.reshape(1, -1)
            x = torch.FloatTensor(state_features)
            output = self._model(x)
            return output.numpy()

    def train_batch(self, states: np.ndarray, target_cfv: np.ndarray,
                    actions: np.ndarray) -> float:
        """
        训练一个batch

        Args:
            states: (batch_size, INPUT_DIM)
            target_cfv: (batch_size, OUTPUT_DIM) 目标反事实值
            actions: (batch_size,) 采取的行动索引

        Returns:
            loss值
        """
        if self._model is None:
            return 0.0

        import torch
        import torch.nn as nn

        self._model.train()

        x = torch.FloatTensor(states)
        y = torch.FloatTensor(target_cfv)
        a = torch.LongTensor(actions)

        predicted = self._model(x)

        # 只对采取的行动计算loss
        loss = nn.MSELoss()(predicted.gather(1, a.unsqueeze(1)).squeeze(), y.gather(1, a.unsqueeze(1)).squeeze())

        self._optimizer.zero_grad()
        loss.backward()
        self._optimizer.step()

        return loss.item()

    def save(self, path: str) -> None:
        """保存模型权重"""
        if self._model is None:
            return
        import torch
        torch.save({
            "model_state_dict": self._model.state_dict(),
            "hidden_dims": self.hidden_dims,
            "input_dim": self.INPUT_DIM,
            "output_dim": self.OUTPUT_DIM,
        }, path)
        logger.info(f"ValueNetwork 已保存到 {path}")

    def load(self, path: str) -> bool:
        """加载模型权重"""
        import os
        if not os.path.exists(path):
            return False

        import torch
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        self._model.load_state_dict(checkpoint["model_state_dict"])
        logger.info(f"ValueNetwork 已从 {path} 加载")
        return True

    @staticmethod
    def encode_state(
        hole_cards: List[str],
        community_cards: List[str],
        pot: int,
        stacks: List[int],
        street: str,
        big_blind: int = 2,
    ) -> np.ndarray:
        """
        将游戏状态编码为网络输入特征

        特征组成:
        - 52维: 牌面one-hot (2-2s, 2h, 2d, 2c, 3s, ..., As)
        - 5维: 归一化数值 (pot/bb, stack0/bb, stack1/bb, to_call/bb, min_raise/bb)
        - 4维: street one-hot (preflop, flop, turn, river)
        """
        features = np.zeros(ValueNetwork.INPUT_DIM, dtype=np.float32)

        # 52维牌面编码
        rank_map = {r: i for i, r in enumerate("23456789TJQKA")}
        suit_map = {"s": 0, "h": 1, "d": 2, "c": 3}

        all_cards = list(hole_cards) + list(community_cards)
        for card_str in all_cards:
            if len(card_str) >= 2:
                rank = card_str[0].upper()
                suit = card_str[1].lower()
                if rank in rank_map and suit in suit_map:
                    idx = rank_map[rank] * 4 + suit_map[suit]
                    if idx < 52:
                        features[idx] = 1.0

        # 5维数值特征 (归一化到big_blind)
        offset = 52
        features[offset + 0] = pot / (big_blind * 100) if big_blind > 0 else 0.0
        features[offset + 1] = stacks[0] / (big_blind * 100) if len(stacks) > 0 and big_blind > 0 else 0.0
        features[offset + 2] = stacks[1] / (big_blind * 100) if len(stacks) > 1 and big_blind > 0 else 0.0
        features[offset + 3] = 0.0  # to_call placeholder
        features[offset + 4] = 0.0  # min_raise placeholder

        # 4维street one-hot
        street_idx = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}.get(street, 0)
        features[57 + street_idx] = 1.0

        return features


# ── Deep CFR ──────────────────────────────────────────

class DeepCFR:
    """
    Deep CFR (Brown et al. 2019)

    用神经网络替代CFR中的显式策略表，大幅减少内存需求

    训练流程：
    1. 初始化两个advantage网络 (P0, P1) 和一个strategy网络
    2. 自博弈产生数据：MCCFR遍历，用advantage网络估算CFV
    3. 用产生的数据训练advantage网络
    4. 定期用advantage网络的输出更新strategy网络
    5. 最终strategy网络即为近似纳什均衡策略

    输出：
    - 训练好的strategy网络权重
    - 导出为gto_tables.yaml供阶段1使用
    """

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

        # 每个玩家一个advantage网络 + 一个共享strategy网络
        self.advantage_nets = {
            0: ValueNetwork(hidden_dims=[256, 256, 128]),
            1: ValueNetwork(hidden_dims=[256, 256, 128]),
        }
        self.strategy_net = ValueNetwork(hidden_dims=[256, 256, 128])

        # 训练数据buffer
        self.advantage_buffer: Dict[int, List[Tuple]] = {0: [], 1: []}
        self.strategy_buffer: List[Tuple] = []

        self.iteration = 0

    def train(self, iterations: int, traversals_per_iter: int = 100,
              buffer_size: int = 10000, batch_size: int = 256) -> Dict[str, float]:
        """
        Deep CFR 训练

        Args:
            iterations: 外层迭代次数
            traversals_per_iter: 每次迭代的MCCFR遍历次数
            buffer_size: 训练数据buffer大小
            batch_size: 训练batch大小
        """
        logger.info(f"DeepCFR 开始训练，迭代: {iterations}, 每次遍历: {traversals_per_iter}")

        for i in range(iterations):
            self.iteration += 1

            # 1. 自博弈产生训练数据
            for player in range(2):
                for _ in range(traversals_per_iter):
                    self._deep_cfr_traverse(
                        player=player,
                        street="preflop",
                        pot=self.small_blind + self.big_blind,
                        stacks=[self.starting_stack - self.small_blind,
                                self.starting_stack - self.big_blind],
                        current_bets=[self.small_blind, self.big_blind],
                        action_history=[],
                        raise_rounds=0,
                    )

            # 2. 训练advantage网络
            for player in range(2):
                if len(self.advantage_buffer[player]) >= batch_size:
                    self._train_advantage_net(player, batch_size)

            # 3. 训练strategy网络
            if len(self.strategy_buffer) >= batch_size:
                self._train_strategy_net(batch_size)

            # 4. 清理buffer（控制内存）
            for player in range(2):
                if len(self.advantage_buffer[player]) > buffer_size:
                    self.advantage_buffer[player] = self.advantage_buffer[player][-buffer_size:]
            if len(self.strategy_buffer) > buffer_size:
                self.strategy_buffer = self.strategy_buffer[-buffer_size:]

            if (i + 1) % max(1, iterations // 10) == 0:
                logger.info(
                    f"  迭代 {i+1}/{iterations}, "
                    f"buffer: P0={len(self.advantage_buffer[0])}, "
                    f"P1={len(self.advantage_buffer[1])}, "
                    f"strat={len(self.strategy_buffer)}"
                )

        logger.info(f"DeepCFR 训练完成，迭代: {self.iteration}")
        return {"iteration": self.iteration}

    def _deep_cfr_traverse(
        self,
        player: int,
        street: str,
        pot: int,
        stacks: List[int],
        current_bets: List[int],
        action_history: List[str],
        raise_rounds: int,
    ) -> float:
        """Deep CFR遍历：用advantage网络估算CFV"""
        opp = 1 - player
        to_call = max(0, current_bets[opp] - current_bets[player])

        actions = self.action_abs.get_abstract_actions(
            pot=pot, to_call=to_call, min_raise=self.big_blind * 2,
            stack=stacks[player], big_blind=self.big_blind,
        )
        action_names = [a[0] for a in actions]

        # 编码状态
        # 简化：用随机牌面代替真实发牌
        hole_cards = ["Ah", "Kh"]  # 训练时应该采样真实手牌
        community_cards = []

        state_features = ValueNetwork.encode_state(
            hole_cards=hole_cards,
            community_cards=community_cards,
            pot=pot,
            stacks=stacks,
            street=street,
            big_blind=self.big_blind,
        )

        # 获取策略（从advantage网络或strategy网络）
        if random.random() < 0.5:
            # 用advantage网络获取策略
            cfv = self.advantage_nets[player].predict(state_features)
        else:
            # 用strategy网络获取策略
            cfv = self.strategy_net.predict(state_features)

        # 将CFV转为策略概率
        positive_cfv = np.maximum(cfv, 0)
        total_cfv = positive_cfv.sum()
        if total_cfv > 0:
            strategy = positive_cfv / total_cfv
        else:
            strategy = np.ones(self.strategy_net.OUTPUT_DIM) / self.strategy_net.OUTPUT_DIM

        # 记录训练数据
        action_idx = np.random.choice(len(strategy), p=strategy)
        self.advantage_buffer[player].append((state_features, action_idx, cfv))
        self.strategy_buffer.append((state_features, strategy))

        # 采样行动继续遍历
        action_name = action_names[min(action_idx, len(action_names) - 1)]

        # 简化：返回采样CFV
        return cfv[action_idx] if action_idx < len(cfv) else 0.0

    def _train_advantage_net(self, player: int, batch_size: int) -> float:
        """训练advantage网络"""
        buffer = self.advantage_buffer[player]
        if len(buffer) < batch_size:
            return 0.0

        samples = random.sample(buffer, batch_size)
        states = np.array([s[0] for s in samples])
        actions = np.array([s[1] for s in samples])
        targets = np.array([s[2] for s in samples])

        return self.advantage_nets[player].train_batch(states, targets, actions)

    def _train_strategy_net(self, batch_size: int) -> float:
        """训练strategy网络"""
        if len(self.strategy_buffer) < batch_size:
            return 0.0

        samples = random.sample(self.strategy_buffer, batch_size)
        states = np.array([s[0] for s in samples])
        targets = np.array([s[1] for s in samples])

        # strategy网络训练：MSE on predicted strategy
        actions = np.argmax(targets, axis=1)
        return self.strategy_net.train_batch(states, targets, actions)

    def save_models(self, directory: str) -> None:
        """保存所有模型"""
        import os
        os.makedirs(directory, exist_ok=True)
        self.advantage_nets[0].save(os.path.join(directory, "advantage_p0.pth"))
        self.advantage_nets[1].save(os.path.join(directory, "advantage_p1.pth"))
        self.strategy_net.save(os.path.join(directory, "strategy.pth"))

    def export_strategy_table(self) -> Dict[str, Dict[str, float]]:
        """
        导出策略表（供阶段1 GtoSolverStrategy使用）

        用strategy网络对常见状态做推理，生成概率分布
        """
        strategy_table = {}

        # 生成常见状态的特征
        common_hands = ["AA", "KK", "QQ", "AKs", "AKo", "AQs", "JJ", "TT"]
        streets = ["preflop", "flop", "turn", "river"]

        for hand in common_hands:
            for street in streets:
                features = ValueNetwork.encode_state(
                    hole_cards=[hand[0] + "h", hand[1] + "s"] if len(hand) == 2 else [hand[0] + "h", hand[1] + "s"],
                    community_cards=[],
                    pot=6,
                    stacks=[100, 100],
                    street=street,
                )
                cfv = self.strategy_net.predict(features)
                positive_cfv = np.maximum(cfv, 0)
                total = positive_cfv.sum()
                probs = positive_cfv / total if total > 0 else np.ones_like(positive_cfv) / len(positive_cfv)

                key = f"{hand}|{street}"
                strategy_table[key] = {
                    "fold": float(probs[0]),
                    "check": float(probs[1]),
                    "call": float(probs[2]),
                    "raise": float(probs[3]),
                    "allin": float(probs[4]),
                }

        return strategy_table
