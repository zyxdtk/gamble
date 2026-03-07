import pytest
from src.engine.utils.board_analyzer import BoardAnalyzer

class TestBoardAnalyzer:
    """测试牌面纹理分析器 (BoardAnalyzer)"""

    @pytest.mark.parametrize("board, expected_desc, min_wetness, max_wetness", [
        # 1. 干燥面 (Dry Boards)
        (["2s", "7d", "Jc"], "干燥面", 0.0, 0.2), # 彻底干燥
        (["As", "8d", "3c"], "干燥面", 0.0, 0.2), # A 高干燥面
        
        # 2. 对子面 (Paired Boards)
        (["2s", "2d", "7h"], "对子面", 0.0, 0.4), # 纯对子
        (["Ks", "Kd", "9s"], "对子面 / 有同花听牌", 0.3, 0.6), # 对子 + 同花听牌
        
        # 3. 三条/四条面 (Trips/Quads)
        (["5s", "5d", "5h"], "三条面", 0.0, 0.5), # 三条
        (["Qs", "Qd", "Qh", "Qc"], "四条面", 0.0, 0.5), # 四条
        
        # 4. 同花潜力面 (Flush Potential)
        (["2s", "7s", "Td"], "有同花听牌", 0.3, 0.4), # 2-flush (听牌)
        (["As", "Ks", "2s"], "有同花", 0.7, 1.0),    # 3-flush (已成/极强潜力)
        (["As", "Ks", "Qs", "Js"], "有同花 / 有顺子潜力", 0.9, 1.0), # 4-flush (极润)
        
        # 5. 顺子潜力面 (Straight Potential)
        (["7s", "8h", "Td"], "有顺子潜力", 0.3, 0.5), # 连贯面
        (["Ts", "Jh", "Qd"], "有顺子潜力", 0.4, 0.7), # OESD 趋势
        (["As", "2d", "3h"], "有顺子潜力", 0.3, 0.5), # A-low 顺子听牌 (A,2,3)
        
        # 6. 复杂湿润面 (Wet Boards)
        (["9s", "Ts", "Js"], "有同花 / 有顺子潜力", 0.7, 1.0), # 同花顺面 (极润)
        (["6s", "7s", "8d", "Qd"], "有同花听牌 / 有顺子潜力", 0.5, 0.8), # 湿润双听牌
        
        # 7. 特殊情况 (Special)
        ([], "Empty board", 0.0, 0.0), # 空牌面
    ])
    def test_board_textures(self, board, expected_desc, min_wetness, max_wetness):
        """
        验证各种牌面纹理的识别和湿润度计算
        """
        analyzer = BoardAnalyzer()
        result = analyzer.analyze(board)
        
        # 1. 牌面描述校验
        if board:
            assert expected_desc in result["description"]
        else:
            assert result["description"] == "Empty board"
            
        # 2. 湿润度范围校验
        assert min_wetness <= result["wetness"] <= max_wetness

        # 校验接口中不应再包含冗余字段
        assert "is_paired" not in result
        assert "flush_potential" not in result
        assert "straight_potential" not in result
