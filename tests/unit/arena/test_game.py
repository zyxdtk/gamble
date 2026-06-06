import pytest
from src.arena.game import GameEngine, ActionType, Street

def test_game_initialization():
    players = [{'name': 'A', 'stack': 1000}, {'name': 'B', 'stack': 1000}]
    engine = GameEngine(players)
    assert len(engine.players) == 2
    assert engine.players[0].stack == 1000

def test_post_blinds():
    players = [{'name': 'A', 'stack': 1000}, {'name': 'B', 'stack': 1000}]
    engine = GameEngine(players, small_blind=1, big_blind=2)
    engine.reset_hand(dealer_idx=0)
    
    # 2人局: SB 是庄家(0), BB 是庄家后一个(1)
    next_actor = engine.post_blinds()
    assert engine.players[0].stack == 999
    assert engine.players[1].stack == 998
    assert engine.pot == 3
    assert next_actor == 0 # 翻牌前由 SB 开始

def test_basic_betting_and_fold():
    players = [{'name': 'A', 'stack': 1000}, {'name': 'B', 'stack': 1000}]
    engine = GameEngine(players, small_blind=1, big_blind=2)
    engine.reset_hand(dealer_idx=0)
    engine.post_blinds()
    
    # 座位 0 (SB) 弃牌
    engine.execute_action(0, ActionType.FOLD)
    assert not engine.players[0].is_active
    
    # 结算
    winners = engine.get_winners()
    assert len(winners) == 1
    assert winners[0][0] == 1 # 1 号位赢
    assert winners[0][1] == 3 # 赢到底池 3

def test_pot_settlement_showdown():
    players = [{'name': 'A', 'stack': 1000}, {'name': 'B', 'stack': 1000}]
    engine = GameEngine(players, small_blind=1, big_blind=2)
    engine.reset_hand(dealer_idx=0)
    engine.post_blinds()
    
    # 模拟大家跟注进入河牌
    engine.execute_action(0, ActionType.CALL) # 跟 1 进入平衡
    engine.next_street() # Flop
    engine.next_street() # Turn
    engine.next_street() # River
    
    # 给定固定牌以确定赢家
    from treys import Card
    engine.players[0].hole_cards = [Card.new('As'), Card.new('Ad')] # AA
    engine.players[1].hole_cards = [Card.new('2s',), Card.new('7d')] # 垃圾牌
    engine.community_cards = [Card.new('Qs'), Card.new('Jd'), Card.new('5h'), Card.new('3c'), Card.new('8s')]
    
    winners = engine.get_winners()
    assert winners[0][0] == 0 # A (AA) 应该赢
    assert winners[0][1] == 4 # SB 1 + BB 2 + CALL 1 = 4
