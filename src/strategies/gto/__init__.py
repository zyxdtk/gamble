"""
GTO求解器包：CFR/DeepCFR 算法实现

架构定位：离线训练 → 输出策略表 → 灌给阶段1 GtoSolverStrategy
不直接参与在线决策，是"策略的老师"

训练流程:
  1. 运行 scripts/train_gto_cfr.py 训练CFR
  2. 自动导出到 config/gto_tables.yaml
  3. GtoSolverStrategy 运行时查表使用
"""

from .abstraction import CardAbstraction, ActionAbstraction, InfoSet, compute_action_history_hash
from .game_tree import GameTree, TreeNode
from .cfr import VanillaCFR, CFRPlus, MCCFR, regret_matching
from .solver import GTOSolver

__all__ = [
    'CardAbstraction', 'ActionAbstraction', 'InfoSet', 'compute_action_history_hash',
    'GameTree', 'TreeNode',
    'VanillaCFR', 'CFRPlus', 'MCCFR', 'regret_matching',
    'GTOSolver',
]

# DeepCFR 延迟导入（需要torch）
def __getattr__(name):
    if name == 'DeepCFR':
        from .deep_cfr import DeepCFR
        return DeepCFR
    if name == 'ValueNetwork':
        from .deep_cfr import ValueNetwork
        return ValueNetwork
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
