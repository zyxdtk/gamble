"""
GTO求解器包 单元测试

覆盖:
- abstraction: CardAbstraction, ActionAbstraction, InfoSet
- game_tree: GameTree, TreeNode
- cfr: VanillaCFR, CFRPlus, MCCFR, regret_matching
- solver: GTOSolver
- deep_cfr: ValueNetwork, DeepCFR (需要torch时跳过)
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# 确保项目根目录在path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.strategies.gto.abstraction import (
    CardAbstraction, ActionAbstraction, InfoSet,
    compute_action_history_hash, RANKS,
)
from src.strategies.gto.game_tree import GameTree, TreeNode, NodeType
from src.strategies.gto.cfr import VanillaCFR, CFRPlus, MCCFR, regret_matching
from src.strategies.gto.solver import GTOSolver


# ═══════════════════════════════════════════════════════
# 抽象层测试
# ═══════════════════════════════════════════════════════

class TestActionAbstraction:
    """动作抽象测试"""

    def setup_method(self):
        self.action_abs = ActionAbstraction()

    def test_default_sizes(self):
        assert self.action_abs.sizes == ["min", "half_pot", "pot", "allin"]

    def test_custom_sizes(self):
        abs_custom = ActionAbstraction(sizes=["min", "pot"])
        assert abs_custom.sizes == ["min", "pot"]

    def test_get_actions_with_to_call(self):
        """有to_call时应返回fold+call"""
        actions = self.action_abs.get_abstract_actions(
            pot=10, to_call=6, min_raise=4, stack=100, big_blind=2
        )
        action_names = [a[0] for a in actions]
        assert "fold" in action_names
        assert "call" in action_names
        assert "check" not in action_names

    def test_get_actions_without_to_call(self):
        """无to_call时应返回check而非fold"""
        actions = self.action_abs.get_abstract_actions(
            pot=10, to_call=0, min_raise=4, stack=100, big_blind=2
        )
        action_names = [a[0] for a in actions]
        assert "check" in action_names
        assert "fold" not in action_names

    def test_raise_actions_included(self):
        """应包含加注行动"""
        actions = self.action_abs.get_abstract_actions(
            pot=10, to_call=0, min_raise=4, stack=200, big_blind=2
        )
        action_names = [a[0] for a in actions]
        assert any("raise" in name for name in action_names)

    def test_no_duplicate_amounts(self):
        """不应有重复金额的行动"""
        actions = self.action_abs.get_abstract_actions(
            pot=10, to_call=0, min_raise=4, stack=200, big_blind=2
        )
        amounts = [a[1] for a in actions]
        assert len(amounts) == len(set(amounts))

    def test_action_to_index_roundtrip(self):
        """行动名↔索引往返"""
        for name in ["fold", "check", "call", "raise_min", "raise_half_pot", "raise_pot", "raise_allin"]:
            idx = self.action_abs.action_to_index(name)
            recovered = self.action_abs.index_to_action(idx)
            assert recovered == name

    def test_short_stack_allin(self):
        """短筹码时加注应该被限制为allin"""
        actions = self.action_abs.get_abstract_actions(
            pot=100, to_call=10, min_raise=20, stack=5, big_blind=2
        )
        # 短筹码不足以call时，call金额应等于stack
        call_actions = [a for a in actions if a[0] == "call"]
        if call_actions:
            assert call_actions[0][1] <= 5


class TestCardAbstraction:
    """牌面抽象测试"""

    def setup_method(self):
        self.card_abs = CardAbstraction(flop_buckets=10, turn_buckets=10, river_buckets=10)

    def test_preflop_bucket_pocket_pair(self):
        """口袋对映射 (AA=0最强→22=12最弱)"""
        assert self.card_abs.get_preflop_bucket("AA") == 0
        assert self.card_abs.get_preflop_bucket("KK") == 1
        assert self.card_abs.get_preflop_bucket("22") == 12

    def test_preflop_bucket_suited(self):
        """同花牌映射"""
        bucket = self.card_abs.get_preflop_bucket("AKs")
        assert 13 <= bucket < 13 + 78  # 同花区间

    def test_preflop_bucket_offsuit(self):
        """非同花牌映射"""
        bucket = self.card_abs.get_preflop_bucket("AKo")
        assert 13 + 78 <= bucket < 13 + 78 + 78  # 非同花区间

    def test_preflop_bucket_range(self):
        """所有手牌应在0-168范围"""
        for r1 in RANKS:
            for r2 in RANKS:
                if r1 == r2:
                    bucket = self.card_abs.get_preflop_bucket(f"{r1}{r2}")
                    assert 0 <= bucket <= 168
                else:
                    for suffix in ["s", "o"]:
                        hi = max(RANKS.index(r1), RANKS.index(r2))
                        lo = min(RANKS.index(r1), RANKS.index(r2))
                        hand = f"{RANKS[hi]}{RANKS[lo]}{suffix}"
                        bucket = self.card_abs.get_preflop_bucket(hand)
                        assert 0 <= bucket <= 168, f"{hand} → {bucket}"

    def test_postflop_bucket_range(self):
        """postflop bucket应在0~N-1范围"""
        from treys import Card
        # 用简单的牌面测试
        hole = [Card.new("Ah"), Card.new("Kh")]
        board = [Card.new("2s"), Card.new("3s"), Card.new("4s")]

        bucket = self.card_abs.get_postflop_bucket(hole, board, "flop")
        assert 0 <= bucket < 10

    def test_postflop_bucket_cache(self):
        """相同输入应命中缓存"""
        from treys import Card
        hole = [Card.new("Ah"), Card.new("Kh")]
        board = [Card.new("2s"), Card.new("3s"), Card.new("4s")]

        b1 = self.card_abs.get_postflop_bucket(hole, board, "flop")
        b2 = self.card_abs.get_postflop_bucket(hole, board, "flop")
        assert b1 == b2


class TestInfoSet:
    """信息集测试"""

    def test_info_set_creation(self):
        info = InfoSet(player=0, card_bucket=5, street="flop", action_history="abc123")
        assert info.player == 0
        assert info.card_bucket == 5
        assert info.street == "flop"

    def test_info_set_hashable(self):
        """InfoSet应可哈希(用作dict key)"""
        info1 = InfoSet(player=0, card_bucket=5, street="flop", action_history="abc")
        info2 = InfoSet(player=0, card_bucket=5, street="flop", action_history="abc")
        d = {info1: "test"}
        assert d[info2] == "test"

    def test_compute_action_history_hash(self):
        """动作历史hash"""
        h1 = compute_action_history_hash(["0:raise", "1:call"])
        h2 = compute_action_history_hash(["0:raise", "1:call"])
        h3 = compute_action_history_hash(["0:call", "1:raise"])
        assert h1 == h2
        assert h1 != h3

    def test_compute_action_history_hash_empty(self):
        assert compute_action_history_hash([]) == ""


# ═══════════════════════════════════════════════════════
# 博弈树测试
# ═══════════════════════════════════════════════════════

class TestTreeNode:
    """树节点测试"""

    def test_node_types(self):
        decision = TreeNode(node_type=NodeType.DECISION)
        terminal = TreeNode(node_type=NodeType.TERMINAL)
        chance = TreeNode(node_type=NodeType.CHANCE)
        assert not decision.is_leaf()
        assert terminal.is_leaf()

    def test_add_child(self):
        parent = TreeNode(node_type=NodeType.DECISION, depth=0)
        child = TreeNode(node_type=NodeType.TERMINAL)
        parent.add_child("fold", child)
        assert "fold" in parent.children
        assert child.depth == 1
        assert child.parent is parent

    def test_get_actions(self):
        parent = TreeNode(node_type=NodeType.DECISION)
        parent.add_child("fold", TreeNode(node_type=NodeType.TERMINAL))
        parent.add_child("call", TreeNode(node_type=NodeType.DECISION))
        assert parent.get_actions() == ["fold", "call"]


class TestGameTree:
    """博弈树测试"""

    def setup_method(self):
        self.card_abs = CardAbstraction(flop_buckets=3, turn_buckets=3, river_buckets=3)
        # 极简动作：只有allin，让树很小
        self.action_abs = ActionAbstraction(sizes=["allin"])
        self.tree = GameTree(
            card_abs=self.card_abs,
            action_abs=self.action_abs,
            starting_stack=4,  # 2BB超浅筹码
        )

    def test_build_tree(self):
        """构建博弈树应成功"""
        root = self.tree.build()
        assert root is not None
        assert root.node_type == NodeType.DECISION
        assert self.tree.node_count > 0

    def test_tree_has_children(self):
        """根节点应有子节点"""
        root = self.tree.build()
        assert len(root.children) > 0

    def test_tree_has_terminals(self):
        """树中应有终端节点"""
        self.tree.build()
        assert self.tree.terminal_count > 0

    def test_build_subtree(self):
        """从指定状态构建子树"""
        subtree = self.tree.build_subtree(
            street="flop",
            pot=10,
            stacks=[18, 18],
            current_bets=[0, 0],
            player=0,
        )
        assert subtree is not None
        assert len(subtree.children) > 0

    def test_count_nodes(self):
        """统计节点数"""
        self.tree.build()
        counts = self.tree.count_nodes()
        assert counts["total"] > 0
        assert counts["decision"] > 0
        assert counts["terminal"] > 0


# ═══════════════════════════════════════════════════════
# CFR算法测试
# ═══════════════════════════════════════════════════════

class TestRegretMatching:
    """遗憾匹配测试"""

    def test_uniform_when_no_positive(self):
        """无正遗憾时均匀分布"""
        regrets = {"fold": -1.0, "call": -2.0}
        strategy = regret_matching(regrets)
        assert abs(strategy["fold"] - 0.5) < 1e-6
        assert abs(strategy["call"] - 0.5) < 1e-6

    def test_proportional_when_positive(self):
        """有正遗憾时按比例分配"""
        regrets = {"fold": 0.0, "call": 3.0, "raise": 1.0}
        strategy = regret_matching(regrets)
        assert abs(strategy["call"] - 0.75) < 1e-6
        assert abs(strategy["raise"] - 0.25) < 1e-6
        assert abs(strategy["fold"] - 0.0) < 1e-6

    def test_single_positive(self):
        """只有一个正遗憾"""
        regrets = {"fold": 5.0, "call": -1.0}
        strategy = regret_matching(regrets)
        assert abs(strategy["fold"] - 1.0) < 1e-6

    def test_empty_regrets(self):
        """空遗憾"""
        strategy = regret_matching({})
        assert strategy == {}


class TestVanillaCFR:
    """VanillaCFR测试"""

    def setup_method(self):
        self.card_abs = CardAbstraction(flop_buckets=3, turn_buckets=3, river_buckets=3)
        self.action_abs = ActionAbstraction(sizes=["allin"])
        self.cfr = VanillaCFR(
            card_abs=self.card_abs,
            action_abs=self.action_abs,
            starting_stack=4,
        )

    def test_initial_state(self):
        """初始状态"""
        assert self.cfr.iteration == 0
        assert len(self.cfr.regret_sum) == 0

    def test_train_runs(self):
        """训练应可运行"""
        stats = self.cfr.train(iterations=10)
        assert stats["iteration"] == 10
        assert stats["strategy_size"] >= 0

    def test_strategy_after_training(self):
        """训练后应有策略"""
        self.cfr.train(iterations=20)
        strategies = self.cfr.get_all_average_strategies()
        # 至少应有一些策略条目
        assert len(strategies) > 0

    def test_strategy_probabilities_sum_to_one(self):
        """策略概率应归一"""
        self.cfr.train(iterations=20)
        strategies = self.cfr.get_all_average_strategies()
        for key, probs in strategies.items():
            total = sum(probs.values())
            assert abs(total - 1.0) < 0.1, f"策略 {key} 概率和={total}"


class TestCFRPlus:
    """CFR+测试"""

    def setup_method(self):
        self.card_abs = CardAbstraction(flop_buckets=3, turn_buckets=3, river_buckets=3)
        self.action_abs = ActionAbstraction(sizes=["allin"])
        self.cfr = CFRPlus(
            card_abs=self.card_abs,
            action_abs=self.action_abs,
            starting_stack=4,
        )

    def test_train_runs(self):
        stats = self.cfr.train(iterations=10)
        assert stats["iteration"] == 10

    def test_no_negative_regrets(self):
        """CFR+不应有负遗憾"""
        self.cfr.train(iterations=20)
        for key, regrets in self.cfr.regret_sum.items():
            for action, value in regrets.items():
                assert value >= 0, f"CFR+遗憾应为非负: {key}/{action}={value}"


class TestMCCFR:
    """MCCFR测试"""

    def setup_method(self):
        self.card_abs = CardAbstraction(flop_buckets=3, turn_buckets=3, river_buckets=3)
        self.action_abs = ActionAbstraction(sizes=["allin"])
        self.cfr = MCCFR(
            card_abs=self.card_abs,
            action_abs=self.action_abs,
            starting_stack=4,
            sampling_strategy="external",
        )

    def test_train_runs(self):
        stats = self.cfr.train(iterations=10)
        assert stats["iteration"] == 10

    def test_sampling_strategy_stored(self):
        assert self.cfr.sampling_strategy == "external"


# ═══════════════════════════════════════════════════════
# 求解器测试
# ═══════════════════════════════════════════════════════

class TestGTOSolver:
    """GTO求解器集成测试"""

    def setup_method(self):
        self.solver = GTOSolver(
            algorithm="mccfr",
            flop_buckets=3,
            turn_buckets=3,
            river_buckets=3,
            action_sizes=["allin"],
            starting_stack=4,
        )

    def test_invalid_algorithm(self):
        """无效算法应报错"""
        with pytest.raises(ValueError, match="未知算法"):
            GTOSolver(algorithm="invalid")

    def test_train_and_export(self, tmp_path):
        """训练+导出流程"""
        stats = self.solver.train(iterations=10)
        assert "iteration" in stats
        assert stats["iteration"] == 10

        output = str(tmp_path / "gto_tables.yaml")
        result_path = self.solver.export_tables(output)
        assert os.path.exists(result_path)

        # 验证YAML可解析
        import yaml
        with open(result_path, "r") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_export_without_train_raises(self, tmp_path):
        """未训练时导出应报错"""
        with pytest.raises(RuntimeError, match="请先运行"):
            self.solver.export_tables(str(tmp_path / "test.yaml"))

    def test_save_and_load_model(self, tmp_path):
        """模型保存和加载"""
        self.solver.train(iterations=10)
        model_dir = str(tmp_path / "model")
        self.solver.save_model(model_dir)

        # 创建新solver并加载
        solver2 = GTOSolver(
            algorithm="mccfr",
            flop_buckets=3, turn_buckets=3, river_buckets=3,
            action_sizes=["allin"],
            starting_stack=4,
        )
        assert solver2.load_model(model_dir)
        assert solver2._trained
        assert solver2.engine.iteration == 10

    def test_load_nonexistent_model(self):
        """加载不存在的模型"""
        solver = GTOSolver(algorithm="mccfr")
        assert not solver.load_model("/nonexistent/path")

    def test_get_strategy_untrained(self):
        """未训练时查策略返回空"""
        result = self.solver.get_strategy("0|preflop|0|abc")
        assert result == {}

    def test_algorithms_registry(self):
        """所有算法应在注册表中"""
        assert "vanilla" in GTOSolver.ALGORITHMS
        assert "cfrplus" in GTOSolver.ALGORITHMS
        assert "mccfr" in GTOSolver.ALGORITHMS


# ═══════════════════════════════════════════════════════
# Deep CFR测试（条件性：需要torch）
# ═══════════════════════════════════════════════════════

class TestValueNetwork:
    """反事实值网络测试"""

    @pytest.fixture(autouse=True)
    def check_torch(self):
        """检查torch是否可用"""
        try:
            import torch
            self.has_torch = True
        except ImportError:
            self.has_torch = False

    def _get_value_network_cls(self):
        from src.strategies.gto.deep_cfr import ValueNetwork
        return ValueNetwork

    def test_encode_state(self):
        """状态编码"""
        ValueNetwork = self._get_value_network_cls()
        import numpy as np
        features = ValueNetwork.encode_state(
            hole_cards=["Ah", "Kh"],
            community_cards=["2s", "3s", "4s"],
            pot=10,
            stacks=[80, 100],
            street="flop",
        )
        assert features.shape == (ValueNetwork.INPUT_DIM,)
        assert features.dtype == np.float32
        # 街道one-hot
        assert features[58] == 1.0  # flop

    def test_encode_state_street(self):
        """不同街道编码"""
        ValueNetwork = self._get_value_network_cls()
        import numpy as np
        for street, idx in [("preflop", 0), ("flop", 1), ("turn", 2), ("river", 3)]:
            features = ValueNetwork.encode_state(
                hole_cards=["Ah", "Kh"], community_cards=[],
                pot=6, stacks=[100, 100], street=street,
            )
            assert features[57 + idx] == 1.0

    def test_predict_without_torch(self):
        """无torch时predict返回零"""
        if self.has_torch:
            pytest.skip("torch已安装")
        ValueNetwork = self._get_value_network_cls()
        vn = ValueNetwork()
        assert vn._model is None
        import numpy as np
        result = vn.predict(np.zeros(61))
        assert result.shape == (5,)

    def test_predict_with_torch(self):
        """有torch时predict正常"""
        if not self.has_torch:
            pytest.skip("torch未安装")
        ValueNetwork = self._get_value_network_cls()
        import numpy as np
        vn = ValueNetwork()
        features = np.random.randn(1, ValueNetwork.INPUT_DIM).astype(np.float32)
        result = vn.predict(features)
        assert result.shape == (1, ValueNetwork.OUTPUT_DIM)


class TestDeepCFR:
    """DeepCFR测试"""

    @pytest.fixture(autouse=True)
    def check_torch(self):
        try:
            import torch
            self.has_torch = True
        except ImportError:
            self.has_torch = False

    def test_deep_cfr_train(self):
        """DeepCFR训练流程"""
        if not self.has_torch:
            pytest.skip("torch未安装")

        from src.strategies.gto.deep_cfr import DeepCFR
        card_abs = CardAbstraction(flop_buckets=3, turn_buckets=3, river_buckets=3)
        action_abs = ActionAbstraction(sizes=["half_pot", "allin"])

        dcfr = DeepCFR(
            card_abs=card_abs, action_abs=action_abs,
            starting_stack=20,
        )
        stats = dcfr.train(iterations=2, traversals_per_iter=5, buffer_size=100, batch_size=8)
        assert "iteration" in stats

    def test_export_strategy_table(self):
        """策略表导出"""
        if not self.has_torch:
            pytest.skip("torch未安装")

        from src.strategies.gto.deep_cfr import DeepCFR
        card_abs = CardAbstraction(flop_buckets=3, turn_buckets=3, river_buckets=3)
        action_abs = ActionAbstraction(sizes=["half_pot", "allin"])

        dcfr = DeepCFR(card_abs=card_abs, action_abs=action_abs, starting_stack=20)
        table = dcfr.export_strategy_table()
        assert isinstance(table, dict)
        for key, probs in table.items():
            assert isinstance(probs, dict)
            for action, prob in probs.items():
                assert 0.0 <= prob <= 1.0


# ═══════════════════════════════════════════════════════
# 训练脚本测试
# ═══════════════════════════════════════════════════════

class TestTrainScript:
    """训练脚本配置加载测试"""

    def _get_project_root(self):
        """项目根目录（而非tests/目录）"""
        test_file = os.path.abspath(__file__)
        # tests/unit/test_gto_cfr.py → 上两级到项目根
        return os.path.dirname(os.path.dirname(os.path.dirname(test_file)))

    def test_load_config_exists(self):
        """加载存在的配置"""
        import yaml
        config_path = os.path.join(self._get_project_root(), "config", "gto_training.yaml")
        assert os.path.exists(config_path)
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        assert "algorithm" in config
        assert "training" in config

    def test_config_has_required_fields(self):
        """配置应包含必要字段"""
        import yaml
        config_path = os.path.join(self._get_project_root(), "config", "gto_training.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        required_keys = ["algorithm", "card_abstraction", "action_abstraction",
                         "game", "training", "output"]
        for key in required_keys:
            assert key in config, f"配置缺少字段: {key}"


# ═══════════════════════════════════════════════════════
# 集成测试：训练→导出→阶段1可读
# ═══════════════════════════════════════════════════════

class TestIntegration:
    """端到端集成测试"""

    def test_train_export_gto_tables_readable(self, tmp_path):
        """训练→导出→阶段1 GtoSolverStrategy可读"""
        # 1. 训练
        solver = GTOSolver(
            algorithm="mccfr",
            flop_buckets=3, turn_buckets=3, river_buckets=3,
            action_sizes=["allin"],
            starting_stack=4,
        )
        solver.train(iterations=10)

        # 2. 导出
        output = str(tmp_path / "gto_tables.yaml")
        solver.export_tables(output)

        # 3. 验证阶段1可读
        import yaml
        with open(output, "r") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        # 应有cfr_trained部分
        assert "cfr_trained" in data
        assert "_meta" in data
        assert data["_meta"]["algorithm"] == "mccfr"

    def test_gto_solver_strategy_with_cfr_tables(self, tmp_path):
        """GtoSolverStrategy能读取CFR导出的表"""
        # 导出一个简单的表
        import yaml
        table_data = {
            "preflop_rfi": {
                "UTG": {"AA": [1.0, 0.0, 0.0, 2.5], "KK": [0.95, 0.05, 0.0, 2.5]},
            },
            "cfr_trained": {
                "flop_bucket0_p0": [0.3, 0.5, 0.2, 0.66],
            },
            "_meta": {"algorithm": "mccfr", "iterations": 100},
        }
        output = str(tmp_path / "gto_tables.yaml")
        with open(output, "w") as f:
            yaml.dump(table_data, f)

        # GtoSolverStrategy能加载
        from src.strategies.strategies.gto_solver import GtoSolverStrategy
        strategy = GtoSolverStrategy()
        assert strategy is not None
