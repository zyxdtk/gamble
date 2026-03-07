from typing import List, Dict

class BoardAnalyzer:
    """
    分析公共牌纹理（Board Texture）
    """
    def analyze(self, board: List[str]) -> Dict:
        if not board:
            return {
                "wetness": 0.0,
                "description": "Empty board"
            }

        # 1. 提取点数和花色
        ranks = []
        suits = []
        rank_values = []
        rank_map = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, 
                    "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
        
        for card in board:
            r = card[0].upper()
            s = card[1].lower()
            ranks.append(r)
            suits.append(s)
            rank_values.append(rank_map.get(r, 0))

        # 2. 同花潜力分析
        suit_counts = {}
        for s in suits:
            suit_counts[s] = suit_counts.get(s, 0) + 1
        
        max_suit_count = max(suit_counts.values()) if suit_counts else 0
        has_flush_potential = max_suit_count >= 2 # 2张或以上同花即认为有潜力

        # 3. 重复牌分析 (Pairs/Trips)
        rank_counts = {}
        for r in ranks:
            rank_counts[r] = rank_counts.get(r, 0) + 1
        
        counts = sorted(rank_counts.values(), reverse=True)
        is_paired = counts[0] == 2 if counts else False
        is_trips = counts[0] == 3 if counts else False
        is_quads = counts[0] == 4 if counts else False
        is_two_pair = len([c for c in counts if c == 2]) >= 2
        
        # 4. 顺子潜力分析
        sorted_values = sorted(list(set(rank_values)))
        max_gap = 0
        if len(sorted_values) >= 2:
            max_gap = max(sorted_values) - min(sorted_values)
        
        # 简化判定：如果 3 张牌跨度在 4 以内，或者有 A2345 这种可能
        has_straight_potential = False
        if len(sorted_values) >= 2:
            # 检查 A2345
            if 14 in sorted_values:
                # 至少要有两张 2-5 的小牌 (加上虚拟的 1，长度需 >= 3)
                low_vals = [1] + [v for v in sorted_values if v < 6]
                if len(low_vals) >= 3:
                    has_straight_potential = True
            
            # 检查连续度
            for i in range(len(sorted_values) - 1):
                if sorted_values[i+1] - sorted_values[i] <= 2:
                    has_straight_potential = True
                    break

        # 4. 计算湿润度 (Wetness)
        # 基础计算逻辑：同花张数 + 连贯程度
        wetness = 0.0
        # 同花贡献
        if max_suit_count >= 3:
            wetness += 0.7
        elif max_suit_count == 2:
            wetness += 0.3
            
        # 连贯贡献
        if has_straight_potential:
            wetness += 0.3
            if len(sorted_values) >= 3 and (max(sorted_values) - min(sorted_values) <= 4):
                wetness += 0.1

        # 动态描述 (根据特征拼接)
        desc = []
        if is_quads: desc.append("四条面")
        elif is_trips: desc.append("三条面")
        elif is_two_pair: desc.append("两对象")
        elif is_paired: desc.append("对子面")
        
        if max_suit_count >= 3: desc.append("有同花")
        elif max_suit_count == 2: desc.append("有同花听牌")
        
        if has_straight_potential: desc.append("有顺子潜力")
        
        description = " / ".join(desc) if desc else "干燥面"

        return {
            "wetness": min(1.0, wetness),
            "description": description
        }
