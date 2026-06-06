"""MTT 盲注结构定义"""

from dataclasses import dataclass
from typing import List


@dataclass
class BlindLevel:
    """单个盲注级别"""
    level: int
    sb: int
    bb: int
    ante: int = 0
    duration_hands: int = 10  # 该级别持续的手数

    @property
    def total_blind(self) -> int:
        """每手总盲注（SB + BB + ante * 人数近似）"""
        return self.sb + self.bb + self.ante


@dataclass
class BlindSchedule:
    """盲注升级时间表"""
    levels: List[BlindLevel]

    def current_level(self, hand_idx: int) -> BlindLevel:
        """根据当前手数获取盲注级别"""
        elapsed = 0
        for level in self.levels:
            elapsed += level.duration_hands
            if hand_idx <= elapsed:
                return level
        # 超出预设范围，返回最后一级
        return self.levels[-1]

    def level_index(self, hand_idx: int) -> int:
        """当前盲注级别的索引"""
        elapsed = 0
        for i, level in enumerate(self.levels):
            elapsed += level.duration_hands
            if hand_idx <= elapsed:
                return i
        return len(self.levels) - 1


def create_standard_schedule() -> BlindSchedule:
    """标准盲注结构（每级10手，稳步递增）"""
    levels = [
        BlindLevel(1,  1,   2,   0,  10),
        BlindLevel(2,  2,   4,   0,  10),
        BlindLevel(3,  3,   6,   0,  10),
        BlindLevel(4,  4,   8,   1,  10),
        BlindLevel(5,  5,  10,   1,  10),
        BlindLevel(6,  7,  14,   2,  10),
        BlindLevel(7,  10, 20,   2,  10),
        BlindLevel(8,  15, 30,   3,  10),
        BlindLevel(9,  20, 40,   4,  10),
        BlindLevel(10, 30, 60,   5,  10),
        BlindLevel(11, 40, 80,   8,  10),
        BlindLevel(12, 50, 100, 10,  10),
        BlindLevel(13, 75, 150, 15,  10),
        BlindLevel(14, 100, 200, 20, 10),
        BlindLevel(15, 150, 300, 25, 10),
        BlindLevel(16, 200, 400, 30, 10),
        BlindLevel(17, 300, 600, 50, 10),
        BlindLevel(18, 400, 800, 75, 10),
        BlindLevel(19, 500, 1000, 100, 10),
        BlindLevel(20, 750, 1500, 150, 10),
    ]
    return BlindSchedule(levels)


def create_turbo_schedule() -> BlindSchedule:
    """快速赛盲注结构（每级6手，快速升级）"""
    levels = [
        BlindLevel(1,  1,   2,   0,  6),
        BlindLevel(2,  2,   4,   0,  6),
        BlindLevel(3,  3,   6,   1,  6),
        BlindLevel(4,  5,  10,   1,  6),
        BlindLevel(5,  7,  14,   2,  6),
        BlindLevel(6,  10, 20,   2,  6),
        BlindLevel(7,  15, 30,   3,  6),
        BlindLevel(8,  20, 40,   5,  6),
        BlindLevel(9,  30, 60,   5,  6),
        BlindLevel(10, 50, 100, 10,  6),
        BlindLevel(11, 75, 150, 15,  6),
        BlindLevel(12, 100, 200, 20, 6),
        BlindLevel(13, 150, 300, 25, 6),
        BlindLevel(14, 200, 400, 40, 6),
        BlindLevel(15, 300, 600, 50, 6),
    ]
    return BlindSchedule(levels)


def create_deepstack_schedule() -> BlindSchedule:
    """深筹码赛盲注结构（每级15手，起步更慢）"""
    levels = [
        BlindLevel(1,  1,   2,   0,  15),
        BlindLevel(2,  1,   2,   0,  15),
        BlindLevel(3,  2,   4,   0,  15),
        BlindLevel(4,  2,   4,   0,  15),
        BlindLevel(5,  3,   6,   0,  15),
        BlindLevel(6,  3,   6,   1,  15),
        BlindLevel(7,  4,   8,   1,  15),
        BlindLevel(8,  5,  10,   1,  15),
        BlindLevel(9,  7,  14,   2,  15),
        BlindLevel(10, 10, 20,   2,  15),
        BlindLevel(11, 15, 30,   3,  15),
        BlindLevel(12, 20, 40,   4,  15),
        BlindLevel(13, 25, 50,   5,  15),
        BlindLevel(14, 30, 60,   5,  15),
        BlindLevel(15, 40, 80,   8,  15),
        BlindLevel(16, 50, 100, 10,  15),
        BlindLevel(17, 75, 150, 15,  15),
        BlindLevel(18, 100, 200, 20, 15),
        BlindLevel(19, 150, 300, 25, 15),
        BlindLevel(20, 200, 400, 40, 15),
    ]
    return BlindSchedule(levels)
