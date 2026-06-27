"""
GTO求解器入口

统一接口：
1. 创建CFR/MCCFR/DeepCFR引擎
2. 运行训练
3. 导出策略表到 gto_tables.yaml（供阶段1使用）
4. 保存/加载模型
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional

import yaml

from .abstraction import CardAbstraction, ActionAbstraction
from .cfr import VanillaCFR, CFRPlus, MCCFR

logger = logging.getLogger("gto.solver")


class GTOSolver:
    """
    GTO求解器

    用法:
        solver = GTOSolver(algorithm="mccfr")
        solver.train(iterations=10000)
        solver.export_tables("config/gto_tables.yaml")
    """

    ALGORITHMS = {
        "vanilla": VanillaCFR,
        "cfrplus": CFRPlus,
        "mccfr": MCCFR,
    }

    def __init__(
        self,
        algorithm: str = "mccfr",
        flop_buckets: int = 10,
        turn_buckets: int = 10,
        river_buckets: int = 10,
        action_sizes: Optional[list] = None,
        small_blind: int = 1,
        big_blind: int = 2,
        starting_stack: int = 100,
        num_opponents: int = 1,
    ):
        self.algorithm_name = algorithm
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.starting_stack = starting_stack

        # 抽象层
        self.card_abs = CardAbstraction(
            flop_buckets=flop_buckets,
            turn_buckets=turn_buckets,
            river_buckets=river_buckets,
            num_opponents=num_opponents,
        )
        self.action_abs = ActionAbstraction(sizes=action_sizes)

        # CFR引擎
        if algorithm not in self.ALGORITHMS:
            raise ValueError(f"未知算法: {algorithm}，可选: {list(self.ALGORITHMS.keys())}")

        algo_cls = self.ALGORITHMS[algorithm]
        self.engine = algo_cls(
            card_abs=self.card_abs,
            action_abs=self.action_abs,
            small_blind=small_blind,
            big_blind=big_blind,
            starting_stack=starting_stack,
        )

        # Deep CFR（如果选择）
        self.deep_engine = None

        self._trained = False
        self._train_stats = {}

    def train(self, iterations: int = 10000) -> Dict[str, float]:
        """
        运行训练

        Args:
            iterations: CFR迭代次数

        Returns:
            训练统计
        """
        logger.info(f"开始训练: algorithm={self.algorithm_name}, iterations={iterations}")
        start_time = time.time()

        stats = self.engine.train(iterations)

        elapsed = time.time() - start_time
        stats["elapsed_seconds"] = round(elapsed, 2)
        stats["iterations_per_second"] = round(iterations / elapsed, 1) if elapsed > 0 else 0

        self._trained = True
        self._train_stats = stats

        logger.info(f"训练完成: {stats}")
        return stats

    def train_deep_cfr(self, iterations: int = 100, traversals: int = 100,
                       buffer_size: int = 10000, batch_size: int = 256) -> Dict[str, float]:
        """
        运行Deep CFR训练（需要torch）

        Args:
            iterations: 外层迭代次数
            traversals: 每次迭代的MCCFR遍历数
            buffer_size: 训练数据buffer大小
            batch_size: 训练batch大小
        """
        from .deep_cfr import DeepCFR

        self.deep_engine = DeepCFR(
            card_abs=self.card_abs,
            action_abs=self.action_abs,
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            starting_stack=self.starting_stack,
        )

        logger.info(f"开始DeepCFR训练: iterations={iterations}, traversals={traversals}")
        start_time = time.time()

        stats = self.deep_engine.train(
            iterations=iterations,
            traversals_per_iter=traversals,
            buffer_size=buffer_size,
            batch_size=batch_size,
        )

        elapsed = time.time() - start_time
        stats["elapsed_seconds"] = round(elapsed, 2)
        self._trained = True
        self._train_stats.update(stats)

        logger.info(f"DeepCFR训练完成: {stats}")
        return stats

    def get_strategy(self, info_set_key: str) -> Dict[str, float]:
        """查询单个信息集的策略"""
        if not self._trained:
            return {}

        strategies = self.engine.get_all_average_strategies()
        return strategies.get(info_set_key, {})

    def export_tables(self, output_path: str = "config/gto_tables.yaml") -> str:
        """
        导出策略表到YAML文件

        这是"老师"输出"教材"的关键步骤：
        CFR训练出的策略 → 转换为阶段1 GtoSolverStrategy可查的gto_tables.yaml

        Args:
            output_path: 输出文件路径

        Returns:
            输出文件的绝对路径
        """
        if not self._trained:
            raise RuntimeError("请先运行 train()")

        strategies = self.engine.get_all_average_strategies()

        # 将策略表转换为gto_tables.yaml格式
        gto_tables = self._convert_to_gto_format(strategies)

        # 如果有Deep CFR引擎，合并其输出
        if self.deep_engine:
            deep_table = self.deep_engine.export_strategy_table()
            gto_tables["deep_cfr_supplementary"] = deep_table

        # 写入YAML
        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        with open(abs_path, "w", encoding="utf-8") as f:
            yaml.dump(gto_tables, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"策略表已导出到 {abs_path}，共 {len(strategies)} 个信息集")
        return abs_path

    def save_model(self, directory: str = "data/gto") -> str:
        """保存训练模型（可恢复训练）"""
        import pickle

        abs_dir = os.path.abspath(directory)
        os.makedirs(abs_dir, exist_ok=True)

        model_path = os.path.join(abs_dir, f"cfr_{self.algorithm_name}_model.pkl")
        with open(model_path, "wb") as f:
            pickle.dump({
                "algorithm": self.algorithm_name,
                "regret_sum": dict(self.engine.regret_sum),
                "strategy_sum": dict(self.engine.strategy_sum),
                "iteration": self.engine.iteration,
                "train_stats": self._train_stats,
            }, f)

        # Deep CFR模型
        if self.deep_engine:
            self.deep_engine.save_models(abs_dir)

        logger.info(f"模型已保存到 {abs_dir}")
        return abs_dir

    def load_model(self, directory: str = "data/gto") -> bool:
        """加载已有模型（继续训练或直接导出）"""
        import pickle

        model_path = os.path.join(directory, f"cfr_{self.algorithm_name}_model.pkl")
        if not os.path.exists(model_path):
            return False

        with open(model_path, "rb") as f:
            data = pickle.load(f)

        # 恢复状态
        from collections import defaultdict
        self.engine.regret_sum = defaultdict(lambda: defaultdict(float), data.get("regret_sum", {}))
        self.engine.strategy_sum = defaultdict(lambda: defaultdict(float), data.get("strategy_sum", {}))
        self.engine.iteration = data.get("iteration", 0)
        self._train_stats = data.get("train_stats", {})
        self._trained = True

        logger.info(f"模型已从 {directory} 加载，迭代数: {self.engine.iteration}")
        return True

    def _convert_to_gto_format(self, strategies: Dict[str, Dict[str, float]]) -> dict:
        """
        将CFR输出的策略表转换为gto_tables.yaml格式

        CFR格式: "player|street|bucket|history_hash" → {"fold": 0.1, "call": 0.6, "raise_half_pot": 0.3}
        GTO格式: 见 config/gto_tables.yaml
        """
        # 读取现有gto_tables作为基础（保留人工调整的值）
        existing_path = os.path.join(os.getcwd(), "config", "gto_tables.yaml")
        gto_tables = {}
        if os.path.exists(existing_path):
            with open(existing_path, "r", encoding="utf-8") as f:
                gto_tables = yaml.safe_load(f) or {}

        # 添加CFR训练结果作为补充数据
        cfr_supplementary = {}
        for info_key, probs in strategies.items():
            # 解析信息集键
            parts = info_key.split("|")
            if len(parts) >= 3:
                player, street, bucket = parts[0], parts[1], parts[2]
                cfr_key = f"{street}_bucket{bucket}_p{player}"

                # 转换概率为 [raise, call, fold, raise_size] 格式
                raise_prob = sum(v for k, v in probs.items() if k.startswith("raise") or k == "allin")
                call_prob = probs.get("call", 0.0) + probs.get("check", 0.0)
                fold_prob = probs.get("fold", 0.0)

                # 估算平均加注尺度
                raise_sizes = {k: v for k, v in probs.items() if k.startswith("raise")}
                avg_raise_size = 0.66  # 默认2/3底池
                if raise_sizes:
                    # 从行动名提取尺度
                    for k, v in raise_sizes.items():
                        if "half" in k:
                            avg_raise_size = avg_raise_size * (1 - v) + 0.5 * v
                        elif "pot" in k:
                            avg_raise_size = avg_raise_size * (1 - v) + 1.0 * v
                        elif "min" in k:
                            avg_raise_size = avg_raise_size * (1 - v) + 0.33 * v

                cfr_supplementary[cfr_key] = [
                    round(raise_prob, 3),
                    round(call_prob, 3),
                    round(fold_prob, 3),
                    round(avg_raise_size, 2),
                ]

        gto_tables["cfr_trained"] = cfr_supplementary
        gto_tables["_meta"] = {
            "algorithm": self.algorithm_name,
            "iterations": self.engine.iteration,
            "info_sets": len(strategies),
            "source": "cfr_training",
        }

        return gto_tables
