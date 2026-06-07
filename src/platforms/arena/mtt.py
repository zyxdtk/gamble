"""MTT 多桌锦标赛管理器

完整实现：
- 多桌分配与座位安排
- 淘汰检测
- 盲注升级
- 桌子平衡（拆短桌/并桌）
- 奖金分配
- 实时进度输出
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from .game import PlayerState
from .agent import ArenaAgent
from .blind_schedule import BlindSchedule, BlindLevel, create_standard_schedule, create_turbo_schedule, create_deepstack_schedule
from .table import TournamentTable

arena_logger = logging.getLogger("arena")


@dataclass
class MTTPlayerConfig:
    """参赛者配置"""
    name: str
    strategy: str  # "gto", "range", "exploitative", "checkorfold", "aggressive", "neural", "icm"
    starting_stack: int = 1000
    is_human: bool = False


@dataclass
class PrizePayout:
    """奖金分配结构"""
    # {名次: 奖金比例} 如 {1: 0.50, 2: 0.30, 3: 0.20}
    structure: Dict[int, float]

    @classmethod
    def default(cls, entries: int) -> 'PrizePayout':
        """根据参赛人数生成默认奖金结构"""
        if entries <= 3:
            return cls({1: 0.65, 2: 0.35})
        elif entries <= 6:
            return cls({1: 0.50, 2: 0.30, 3: 0.20})
        elif entries <= 9:
            return cls({1: 0.40, 2: 0.25, 3: 0.18, 4: 0.10, 5: 0.07})
        elif entries <= 18:
            return cls({1: 0.30, 2: 0.20, 3: 0.14, 4: 0.10, 5: 0.08,
                        6: 0.06, 7: 0.05, 8: 0.04, 9: 0.03})
        else:
            return cls({1: 0.25, 2: 0.17, 3: 0.12, 4: 0.09, 5: 0.07,
                        6: 0.05, 7: 0.04, 8: 0.04, 9: 0.03, 10: 0.03})


@dataclass
class MTTConfig:
    """锦标赛配置"""
    entries: int = 18                      # 参赛人数
    entry_fee: int = 100                   # 买入费
    starting_stack: int = 1000             # 起始筹码
    blind_schedule: str = "standard"       # "standard", "turbo", "deepstack"
    prize_structure: Optional[PrizePayout] = None
    table_size: int = 9                    # 每桌最大人数
    late_reg_hands: int = 0                # 迟到注册手数上限
    strategy_distribution: str = "mixed"   # "mixed" 或指定策略名


@dataclass
class MTTPlayerStats:
    """玩家锦标赛统计"""
    player_id: str
    name: str
    strategy: str
    finish_pos: int = 0
    prize_won: int = 0
    total_hands: int = 0
    vpip: float = 0.0
    pfr: float = 0.0
    hands_won: int = 0
    busted_hand: int = 0
    final_stack: int = 0


@dataclass
class MTTReport:
    """锦标赛报告"""
    entries: int
    duration_sec: float
    prize_pool: int
    player_stats: List[MTTPlayerStats]
    total_hands: int
    blind_level_log: List[int] = field(default_factory=list)
    table_count_log: List[int] = field(default_factory=list)


class MTTManager:
    """MTT 多桌锦标赛管理器"""

    def __init__(self, config: MTTConfig):
        self.config = config

        # 盲注表
        schedule_map = {
            "standard": create_standard_schedule,
            "turbo": create_turbo_schedule,
            "deepstack": create_deepstack_schedule,
        }
        creator = schedule_map.get(config.blind_schedule, create_standard_schedule)
        self.blind_schedule = creator()

        # 奖金结构
        if config.prize_structure:
            self.prize_payout = config.prize_structure
        else:
            self.prize_payout = PrizePayout.default(config.entries)

        # 玩家注册表
        self.player_configs: List[MTTPlayerConfig] = []
        self.player_states: Dict[str, PlayerState] = {}  # player_id -> PlayerState
        self.player_agents: Dict[str, ArenaAgent] = {}   # player_id -> ArenaAgent
        self.player_stats: Dict[str, MTTPlayerStats] = {}

        # 桌子
        self.tables: List[TournamentTable] = []

        # 锦标赛状态
        self.elimination_order: List[str] = []  # 淘汰顺序（最早淘汰在前）
        self._global_hand_idx = 0

    def register_players(self, configs: List[MTTPlayerConfig]):
        """注册所有参赛者"""
        strategies = ["gto", "range", "exploitative", "checkorfold", "aggressive"]

        for i, cfg in enumerate(configs):
            player_id = f"mtt_p{i}"
            strategy_name = cfg.strategy
            if strategy_name == "mixed":
                strategy_name = strategies[i % len(strategies)]

            strategy = self._create_strategy(strategy_name)
            agent = ArenaAgent(seat_id=0, strategy=strategy, player_id=player_id)
            agent.name = cfg.name

            ps = PlayerState(seat_id=0, name=cfg.name, stack=cfg.starting_stack)
            ps.player_id = player_id

            self.player_configs.append(cfg)
            self.player_states[player_id] = ps
            self.player_agents[player_id] = agent
            self.player_stats[player_id] = MTTPlayerStats(
                player_id=player_id,
                name=cfg.name,
                strategy=strategy_name,
            )

        arena_logger.info(f"已注册 {len(configs)} 名参赛者")

    def initial_seating(self):
        """初始座位分配：均匀分配到各桌"""
        num_tables = (len(self.player_configs) + self.config.table_size - 1) // self.config.table_size
        self.tables = [TournamentTable(table_id=i, max_seats=self.config.table_size)
                       for i in range(num_tables)]

        # 轮流分配玩家到各桌
        player_ids = list(self.player_states.keys())
        table_idx = 0
        for pid in player_ids:
            table = self.tables[table_idx % num_tables]
            ps = self.player_states[pid]
            agent = self.player_agents[pid]
            seat = table.sit_player(ps, agent)
            if seat >= 0:
                arena_logger.info(f"玩家 {ps.name} 分配至桌子 {table.table_id} 座位 {seat}")
            table_idx += 1

        arena_logger.info(f"初始分配: {num_tables} 桌, {len(player_ids)} 人")

    async def run(self) -> MTTReport:
        """运行完整锦标赛"""
        start_time = time.time()

        if not self.tables:
            self.initial_seating()

        arena_logger.info("=" * 60)
        arena_logger.info(f"MTT 锦标赛开始! 参赛: {len(self.player_configs)} 人")
        arena_logger.info(f"买入: {self.config.entry_fee}, 起始筹码: {self.config.starting_stack}")
        arena_logger.info(f"盲注结构: {self.config.blind_schedule}")
        arena_logger.info("=" * 60)

        self._global_hand_idx = 0
        last_blind_level = -1

        while True:
            remaining = self._count_remaining()

            if remaining <= 1:
                break

            # 先进行桌子平衡，确保玩家在同一桌上
            self._balance_tables()

            # 再次检查（平衡后可能已合并到一桌）
            remaining = self._count_remaining()
            if remaining <= 1:
                break

            # 检查是否有能打牌的桌子（>=2人）
            playable_tables = [t for t in self.tables if t.player_count >= 2]
            if not playable_tables:
                # 所有剩余玩家都无法同桌（异常），强制结束
                arena_logger.warning("无可用桌子，强制结束")
                break

            # 盲注升级
            blind_level = self.blind_schedule.current_level(self._global_hand_idx + 1)
            level_idx = self.blind_schedule.level_index(self._global_hand_idx + 1)
            if level_idx != last_blind_level:
                arena_logger.info(f"--- 盲注升级至 Level {blind_level.level}: "
                                  f"SB={blind_level.sb} BB={blind_level.bb} Ante={blind_level.ante} ---")
                last_blind_level = level_idx

            # 在每张桌上打一手
            all_busted: List[Tuple[str, int]] = []
            for table in self.tables:
                if table.player_count >= 2:
                    busted = await table.play_hand(blind_level)
                    all_busted.extend(busted)

            self._global_hand_idx += 1

            # 处理淘汰
            for pid, _ in all_busted:
                self._handle_bust(pid)

            # 更新统计
            self._update_stats()

            # 进度输出
            if self._global_hand_idx % 5 == 0:
                self._print_progress()

            # 安全上限
            if self._global_hand_idx > 5000:
                arena_logger.warning("超过 5000 手安全上限，强制结束")
                break

        # 设置最终排名
        self._finalize_rankings()

        duration = time.time() - start_time
        prize_pool = self.config.entry_fee * len(self.player_configs)

        report = MTTReport(
            entries=len(self.player_configs),
            duration_sec=duration,
            prize_pool=prize_pool,
            player_stats=sorted(self.player_stats.values(), key=lambda s: s.finish_pos),
            total_hands=self._global_hand_idx,
        )

        self._print_final_report(report)
        return report

    def _create_strategy(self, strategy_type: str):
        """创建策略实例"""
        from src.strategies.strategies.balanced import BalancedStrategy
        from src.strategies.strategies.exploitative import ExploitativeStrategy
        from src.strategies.strategies.range import RangeStrategy
        from src.strategies.strategies.check_or_fold import CheckOrFoldStrategy
        from src.strategies.strategies.aggressive import AggressiveStrategy

        strategy_type = strategy_type.lower()
        if strategy_type in ("balanced", "gto"):
            return BalancedStrategy(thinking_timeout=2.0)
        elif strategy_type == "exploitative":
            return ExploitativeStrategy(thinking_timeout=2.0)
        elif strategy_type == "neural":
            from src.strategies.strategies.neural import NeuralStrategy
            return NeuralStrategy(thinking_timeout=2.0)
        elif strategy_type == "checkorfold":
            return CheckOrFoldStrategy()
        elif strategy_type == "aggressive":
            return AggressiveStrategy(thinking_timeout=2.0)
        elif strategy_type == "icm":
            from src.strategies.strategies.icm import ICMStrategy
            return ICMStrategy(thinking_timeout=2.0)
        else:
            return RangeStrategy(thinking_timeout=2.0)

    def _count_remaining(self) -> int:
        """统计剩余玩家数"""
        return sum(1 for ps in self.player_states.values() if ps.stack > 0)

    def _handle_bust(self, player_id: str):
        """处理淘汰"""
        if player_id in self.player_states and self.player_states[player_id].stack == 0:
            self.elimination_order.append(player_id)
            stats = self.player_stats.get(player_id)
            if stats:
                stats.busted_hand = self._global_hand_idx
                stats.final_stack = 0
            arena_logger.info(f"玩家 {self.player_states[player_id].name} 淘汰! "
                              f"(第 {len(self.elimination_order)} 名淘汰)")

    def _update_stats(self):
        """更新玩家统计"""
        for pid, stats in self.player_stats.items():
            ps = self.player_states.get(pid)
            if ps and ps.stack > 0:
                stats.total_hands += 1
                stats.final_stack = ps.stack

    def _balance_tables(self):
        """桌子平衡：拆短桌、并桌"""
        # 第一步：从所有桌上移除已淘汰（stack==0）的玩家
        for table in self.tables:
            busted_seats = [s for s in range(table.max_seats)
                           if table.seats[s] is not None and table.seats[s].stack == 0]
            for seat_id in busted_seats:
                table.remove_player(seat_id)

        # 移除空桌
        self.tables = [t for t in self.tables if t.player_count > 0]

        if len(self.tables) <= 1:
            return

        # 收集所有不满2人的桌上的玩家
        players_to_move: List[PlayerState] = []
        tables_with_players = []

        for table in self.tables:
            if table.player_count < 2:
                for ps in table.active_players:
                    players_to_move.append(ps)
                    table.remove_player(ps.seat_id)
            else:
                tables_with_players.append(table)

        # 如果没有"有2人以上"的桌子，将所有人合并到一张新桌
        if not tables_with_players and players_to_move:
            new_table = TournamentTable(
                table_id=max((t.table_id for t in self.tables), default=-1) + 1,
                max_seats=self.config.table_size,
            )
            for ps in players_to_move:
                agent = self.player_agents[ps.player_id]
                new_table.sit_player(ps, agent)
            tables_with_players.append(new_table)
            players_to_move = []

        # 将散落玩家安排到有人的桌子
        for ps in players_to_move:
            placed = False
            for table in tables_with_players:
                if table.player_count < table.max_seats:
                    agent = self.player_agents[ps.player_id]
                    table.sit_player(ps, agent)
                    placed = True
                    break
            if not placed and tables_with_players:
                # 强制安排到第一个有人的桌子
                agent = self.player_agents[ps.player_id]
                tables_with_players[0].sit_player(ps, agent)

        self.tables = [t for t in tables_with_players if t.player_count > 0]

        # 如果只剩一桌且有超过 max_seats 人，需要拆分
        if len(self.tables) == 1 and self.tables[0].player_count > self.config.table_size:
            self._split_table(self.tables[0])

    def _split_table(self, table: TournamentTable):
        """拆分过大的桌子"""
        overflow = table.player_count - self.config.table_size
        if overflow <= 0:
            return

        new_table = TournamentTable(
            table_id=len(self.tables),
            max_seats=self.config.table_size,
        )
        self.tables.append(new_table)

        # 将后半部分玩家移到新桌
        players = table.active_players
        for ps in players[self.config.table_size:]:
            table.remove_player(ps.seat_id)
            agent = self.player_agents[ps.player_id]
            new_table.sit_player(ps, agent)

    def _finalize_rankings(self):
        """确定最终排名"""
        total = len(self.player_configs)

        # 淘汰顺序: 最早淘汰 = 最差名次
        for i, pid in enumerate(self.elimination_order):
            finish_pos = total - i
            stats = self.player_stats.get(pid)
            if stats:
                stats.finish_pos = finish_pos

        # 未淘汰的玩家（筹码排名）
        eliminated_set = set(self.elimination_order)
        remaining = [pid for pid in self.player_states
                     if self.player_states[pid].stack > 0 and pid not in eliminated_set]
        if remaining:
            # 按筹码降序排列
            remaining.sort(key=lambda pid: self.player_states[pid].stack, reverse=True)
            for i, pid in enumerate(remaining):
                stats = self.player_stats.get(pid)
                if stats:
                    stats.finish_pos = i + 1
                    stats.final_stack = self.player_states[pid].stack

        # 没有筹码且未在淘汰列表中的（异常情况），放最末
        for pid, stats in self.player_stats.items():
            if stats.finish_pos == 0:
                stats.finish_pos = total
                stats.final_stack = 0

        # 计算奖金
        prize_pool = self.config.entry_fee * len(self.player_configs)
        for stats in self.player_stats.values():
            prize_pct = self.prize_payout.structure.get(stats.finish_pos, 0.0)
            stats.prize_won = int(prize_pool * prize_pct)

    def _print_progress(self):
        """打印进度"""
        remaining = self._count_remaining()
        blind = self.blind_schedule.current_level(self._global_hand_idx + 1)
        table_count = len([t for t in self.tables if t.player_count >= 2])
        arena_logger.info(
            f"[MTT] Hand #{self._global_hand_idx} | "
            f"剩余: {remaining} 人 | {table_count} 桌 | "
            f"盲注: {blind.sb}/{blind.bb}"
        )

    def _print_final_report(self, report: MTTReport):
        """打印最终报告"""
        print("\n" + "=" * 70)
        print(f"  MTT 锦标赛完赛报告")
        print("-" * 70)
        print(f"  参赛人数: {report.entries}  |  奖池: {report.prize_pool}")
        print(f"  总手数: {report.total_hands}  |  耗时: {report.duration_sec:.1f}s")
        print("-" * 70)
        print(f"  {'名次':>4} | {'玩家':<20} | {'策略':<14} | {'奖金':>8} | {'淘汰手':>6}")
        print("-" * 70)

        for ps in report.player_stats:
            prize_str = f"{ps.prize_won}" if ps.prize_won > 0 else "-"
            busted_str = f"#{ps.busted_hand}" if ps.busted_hand > 0 else "冠军!"
            print(f"  {ps.finish_pos:>4} | {ps.name:<20} | {ps.strategy:<14} | {prize_str:>8} | {busted_str:>6}")

        print("=" * 70 + "\n")
