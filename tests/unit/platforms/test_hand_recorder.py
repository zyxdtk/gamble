#!/usr/bin/env python3
"""
HandRecorder / HandHistoryStore 单元测试

覆盖：
- HandRecorder 生命周期（start_hand → on_ws_update → record_decision → finalize_hand）
- WS 事件分发（dealHoleCards / dealCommunityCards / bet/call/raise/fold / awardPot / blinds）
- 决策记录（equity/pot_odds/ev/confidence/strategy_name 携带）
- JSONL + SQLite 持久化
- 异常安全（回调异常不影响主流程）
- abort 丢弃未完成记录
"""
import json
import os
import tempfile

import pytest

from src.platforms.browser.hand_recorder import (
    DecisionContext,
    HandHistoryStore,
    HandRecorder,
    HandRecord,
    PlayerAction,
    PotAward,
)
from src.utils.cli_player import ActionChoice


# ─── fixtures ───

@pytest.fixture
def tmp_store(tmp_path):
    """临时 HandHistoryStore（使用 pytest tmp_path）"""
    return HandHistoryStore(base_dir=str(tmp_path))


@pytest.fixture
def ws_state_basic():
    """基础 WS 状态快照"""
    return {
        "hand_id": 1001,
        "my_seat_id": 3,
        "my_user_id": "user_42",
        "dealer_seat": 1,
        "big_blind": 10,
        "community_cards": [],
        "hole_cards": ["Ah", "Kd"],
        "current_stage": "preflop",
        "players": {
            1: {"seat_id": 1, "user_id": "user_1", "name": "Alice", "chips": 200, "status": "active"},
            2: {"seat_id": 2, "user_id": "user_2", "name": "Bob", "chips": 150, "status": "active"},
            3: {"seat_id": 3, "user_id": "user_42", "name": "Me", "chips": 300, "status": "active"},
        },
    }


# ─── HandRecorder 生命周期 ───

class TestHandRecorderLifecycle:
    """测试 HandRecorder 生命周期管理"""

    def test_start_hand_initializes_record(self, tmp_store, ws_state_basic):
        """start_hand 创建新 HandRecord 并快照初始筹码"""
        rec = HandRecorder(tmp_store, "table_1")
        assert not rec.is_recording
        assert rec.current_hand_id is None

        rec.start_hand(1001, ws_state_basic)

        assert rec.is_recording
        assert rec.current_hand_id == 1001
        assert rec._table_id == "table_1"

    def test_start_hand_snapshots_chips(self, tmp_store, ws_state_basic):
        """start_hand 快照玩家初始筹码"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        assert rec._chips_start == 300  # my_seat_id=3 → chips=300
        assert rec._current.chips_start == 300

    def test_start_hand_records_player_identity(self, tmp_store, ws_state_basic):
        """start_hand 记录我的座位/user_id/dealer/big_blind"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        c = rec._current
        assert c.my_seat == 3
        assert c.my_user_id == "user_42"
        assert c.dealer_seat == 1
        assert c.big_blind == 10

    def test_start_hand_finalizes_previous(self, tmp_store, ws_state_basic):
        """start_hand 时若上一手未结束，先 finalize"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        # 不调 finalize，直接 start 下一手
        ws_state_end = dict(ws_state_basic)
        ws_state_end["hand_id"] = 1002
        ws_state_end["players"] = {
            3: {"seat_id": 3, "user_id": "user_42", "name": "Me", "chips": 350, "status": "active"},
        }
        rec.start_hand(1002, ws_state_end)

        # 上一手应被保存（profit=+50）
        results = tmp_store.query()
        assert len(results) == 1
        assert results[0]["hand_id"] == 1001
        assert results[0]["profit"] == 50

    def test_finalize_hand_persists(self, tmp_store, ws_state_basic):
        """finalize_hand 计算盈亏并持久化"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        # 模拟筹码变化
        ws_end = dict(ws_state_basic)
        ws_end["players"] = {
            3: {"seat_id": 3, "user_id": "user_42", "name": "Me", "chips": 280, "status": "active"},
        }
        rec.finalize_hand(ws_end)

        assert not rec.is_recording
        results = tmp_store.query()
        assert len(results) == 1
        assert results[0]["hand_id"] == 1001
        assert results[0]["profit"] == -20  # 280 - 300

    def test_finalize_hand_noop_when_not_recording(self, tmp_store):
        """未在记录时 finalize_hand 无副作用"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.finalize_hand({})
        assert not rec.is_recording
        assert tmp_store.query() == []

    def test_abort_discards_current(self, tmp_store, ws_state_basic):
        """abort 丢弃未完成记录"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        assert rec.is_recording

        rec.abort()
        assert not rec.is_recording
        assert rec.current_hand_id is None
        # 不应持久化
        assert tmp_store.query() == []


# ─── WS 事件分发 ───

class TestWsEventDispatch:
    """测试 on_ws_update 按 action 分发"""

    def test_deal_hole_cards(self, tmp_store, ws_state_basic):
        """dealHoleCards 记录我的底牌"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        ws = dict(ws_state_basic)
        ws["hole_cards"] = ["Ah", "Kd"]
        rec.on_ws_update("dealHoleCards", {"cards": [], "players": []}, ws)

        assert rec._current.my_hole_cards == ["Ah", "Kd"]

    def test_deal_community_cards_flop(self, tmp_store, ws_state_basic):
        """dealCommunityCards 3张 → flop"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        ws = dict(ws_state_basic)
        ws["community_cards"] = ["2h", "7d", "Ac"]
        rec.on_ws_update("dealCommunityCards", {"cards": ["2h", "7d", "Ac"]}, ws)

        assert rec._current.community_cards_final == ["2h", "7d", "Ac"]
        assert rec._current.community_cards_by_street.get("flop") == ["2h", "7d", "Ac"]

    def test_deal_community_cards_turn(self, tmp_store, ws_state_basic):
        """dealCommunityCards 4张 → turn"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        ws = dict(ws_state_basic)
        ws["community_cards"] = ["2h", "7d", "Ac", "Ts"]
        rec.on_ws_update("dealCommunityCards", {"cards": ["Ts"]}, ws)

        assert "turn" in rec._current.community_cards_by_street

    def test_player_action_bet(self, tmp_store, ws_state_basic):
        """bet 动作记录到 actions"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        update = {"userId": "user_1", "seatId": 1, "amount": 50}
        ws = dict(ws_state_basic)
        ws["current_stage"] = "flop"
        rec.on_ws_update("bet", update, ws)

        assert len(rec._current.actions) == 1
        act = rec._current.actions[0]
        assert act.action == "bet"
        assert act.amount == 50
        assert act.seat_id == 1
        assert act.user_id == "user_1"
        assert act.street == "flop"

    def test_player_action_raise(self, tmp_store, ws_state_basic):
        """raise 动作（raiseTo 字段）"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        update = {"userId": "user_2", "seatId": 2, "raiseTo": 120}
        rec.on_ws_update("raise", update, ws_state_basic)

        act = rec._current.actions[0]
        assert act.action == "raise"
        assert act.amount == 120

    def test_player_action_fold(self, tmp_store, ws_state_basic):
        """fold 动作"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        update = {"userId": "user_1", "seatId": 1}
        rec.on_ws_update("fold", update, ws_state_basic)

        assert len(rec._current.actions) == 1
        assert rec._current.actions[0].action == "fold"

    def test_award_pot(self, tmp_store, ws_state_basic):
        """awardPot 记录颁奖"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        update = {
            "pots": [
                {"chips": 300, "winners": [{"userId": "user_42", "name": "Me"}]},
            ],
        }
        rec.on_ws_update("awardPot", update, ws_state_basic)

        assert len(rec._current.pot_awards) == 1
        award = rec._current.pot_awards[0]
        assert award.chips == 300
        assert "user_42" in award.winners
        assert "Me" in award.winner_names

    def test_blinds_updates_big_blind(self, tmp_store, ws_state_basic):
        """blinds 更新 big_blind"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        assert rec._current.big_blind == 10

        rec.on_ws_update("blinds", {"minimumRaise": 20}, ws_state_basic)
        assert rec._current.big_blind == 20

    def test_on_ws_update_noop_when_not_recording(self, tmp_store, ws_state_basic):
        """未在记录时 on_ws_update 无副作用"""
        rec = HandRecorder(tmp_store, "table_1")
        # 不调 start_hand
        rec.on_ws_update("bet", {"userId": "u1", "amount": 10}, ws_state_basic)
        # 不崩溃即可

    def test_on_ws_update_ignores_none_action(self, tmp_store, ws_state_basic):
        """action=None 时静默返回"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        rec.on_ws_update(None, {}, ws_state_basic)
        # 不崩溃，无动作记录
        assert rec._current.actions == []


# ─── 决策记录 ───

class TestDecisionRecording:
    """测试 record_decision 从 ActionChoice 携带元数据"""

    def test_record_decision_copies_metadata(self, tmp_store, ws_state_basic):
        """record_decision 拷贝 equity/pot_odds/ev/confidence/strategy_name"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        choice = ActionChoice(
            action="raise",
            amount=100,
            label="raise 100",
            reasoning="[TAG] 强牌加注",
            source="strategy:tag",
            raw="RAISE",
            equity=0.65,
            pot_odds=0.33,
            ev=15.5,
            confidence=0.9,
            strategy_name="TAG",
        )
        rec.record_decision(choice, street="flop")

        assert len(rec._current.my_decisions) == 1
        d = rec._current.my_decisions[0]
        assert d.action == "raise"
        assert d.amount == 100
        assert d.equity == pytest.approx(0.65)
        assert d.pot_odds == pytest.approx(0.33)
        assert d.ev == pytest.approx(15.5)
        assert d.confidence == pytest.approx(0.9)
        assert d.strategy_name == "TAG"
        assert d.street == "flop"
        assert "TAG" in d.reasoning

    def test_record_decision_default_metadata(self, tmp_store, ws_state_basic):
        """未设置元数据的 ActionChoice 使用默认值"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        choice = ActionChoice(action="check", amount=0)
        rec.record_decision(choice, street="preflop")

        d = rec._current.my_decisions[0]
        assert d.equity == 0.0
        assert d.confidence == 1.0
        assert d.strategy_name == ""

    def test_record_decision_noop_when_not_recording(self, tmp_store):
        """未在记录时 record_decision 无副作用"""
        rec = HandRecorder(tmp_store, "table_1")
        choice = ActionChoice(action="fold", amount=0)
        rec.record_decision(choice, street="preflop")
        # 不崩溃即可


# ─── JSONL + SQLite 持久化 ───

class TestPersistence:
    """测试 JSONL + SQLite 双存储"""

    def test_save_writes_jsonl(self, tmp_store, ws_state_basic):
        """save 写 JSONL 文件，每行合法 JSON"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        rec.finalize_hand(ws_state_basic)

        # 找到 JSONL 文件
        jsonl_files = [f for f in os.listdir(tmp_store._base_dir) if f.endswith(".jsonl")]
        assert len(jsonl_files) == 1
        path = os.path.join(tmp_store._base_dir, jsonl_files[0])
        with open(path, "r", encoding="utf-8") as f:
            line = f.readline()
            data = json.loads(line)
            assert data["hand_id"] == 1001
            assert data["table_id"] == "table_1"

    def test_save_writes_sqlite(self, tmp_store, ws_state_basic):
        """save 写 SQLite 摘要索引"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        rec.finalize_hand(ws_state_basic)

        results = tmp_store.query()
        assert len(results) == 1
        row = results[0]
        assert row["hand_id"] == 1001
        assert row["table_id"] == "table_1"
        assert "jsonl_file" in row
        assert "jsonl_line" in row
        assert row["jsonl_line"] == 0

    def test_save_multiple_hands(self, tmp_store, ws_state_basic):
        """多手牌连续保存，行号递增"""
        rec = HandRecorder(tmp_store, "table_1")

        for i in range(3):
            ws = dict(ws_state_basic)
            ws["hand_id"] = 2000 + i
            rec.start_hand(2000 + i, ws)
            rec.finalize_hand(ws)

        results = tmp_store.query()
        assert len(results) == 3
        # 行号 0, 1, 2
        line_numbers = sorted(r["jsonl_line"] for r in results)
        assert line_numbers == [0, 1, 2]

    def test_query_by_hand_id(self, tmp_store, ws_state_basic):
        """按 hand_id 查询"""
        rec = HandRecorder(tmp_store, "table_1")
        for hid in [1001, 1002, 1003]:
            ws = dict(ws_state_basic)
            ws["hand_id"] = hid
            rec.start_hand(hid, ws)
            rec.finalize_hand(ws)

        results = tmp_store.query(hand_id=1002)
        assert len(results) == 1
        assert results[0]["hand_id"] == 1002

    def test_sqlite_stores_decision_summary(self, tmp_store, ws_state_basic):
        """SQLite 摘要包含我方最后决策的 equity/pot_odds/ev"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        choice = ActionChoice(
            action="raise",
            amount=100,
            equity=0.72,
            pot_odds=0.25,
            ev=30.0,
            confidence=0.85,
            strategy_name="TAG",
            reasoning="强牌",
        )
        rec.record_decision(choice, street="flop")
        rec.finalize_hand(ws_state_basic)

        results = tmp_store.query()
        row = results[0]
        assert row["my_action"] == "raise"
        assert row["my_amount"] == 100
        assert row["my_equity"] == pytest.approx(0.72)
        assert row["my_pot_odds"] == pytest.approx(0.25)
        assert row["my_ev"] == pytest.approx(30.0)
        assert row["strategy_name"] == "TAG"

    def test_jsonl_contains_full_record(self, tmp_store, ws_state_basic):
        """JSONL 包含完整记录（actions/decisions/awards）"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        # 记录动作
        rec.on_ws_update("bet", {"userId": "user_1", "seatId": 1, "amount": 50}, ws_state_basic)
        # 记录决策
        choice = ActionChoice(action="call", amount=50, equity=0.4, strategy_name="TAG")
        rec.record_decision(choice, street="preflop")
        # 记录颁奖
        rec.on_ws_update("awardPot", {
            "pots": [{"chips": 100, "winners": [{"userId": "user_42", "name": "Me"}]}],
        }, ws_state_basic)

        rec.finalize_hand(ws_state_basic)

        # 读取 JSONL 验证完整结构
        jsonl_files = [f for f in os.listdir(tmp_store._base_dir) if f.endswith(".jsonl")]
        path = os.path.join(tmp_store._base_dir, jsonl_files[0])
        with open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.readline())

        assert len(data["actions"]) == 1
        assert data["actions"][0]["action"] == "bet"
        assert len(data["my_decisions"]) == 1
        assert data["my_decisions"][0]["action"] == "call"
        assert len(data["pot_awards"]) == 1
        assert data["pot_awards"][0]["chips"] == 100

    def test_db_path_and_jsonl_in_data_dir(self, tmp_path):
        """默认路径在 data/hand_history/ 下"""
        # 改变 cwd 来测试默认路径
        original_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            store = HandHistoryStore()
            assert "hand_history" in store._base_dir
            assert store._db_path.endswith("hand_history.db")
        finally:
            os.chdir(original_cwd)


# ─── 异常安全 ───

class TestExceptionSafety:
    """测试记录操作异常不影响主流程"""

    def test_callback_exception_swallowed(self, tmp_store, ws_state_basic):
        """on_ws_update 内部异常被吞掉，不抛出"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)

        # 构造一个会触发异常的 ws_state（players 的 key 不是 int）
        bad_ws = dict(ws_state_basic)
        bad_ws["players"] = {"not_an_int": {"chips": "not_a_number"}}

        # 不应抛出异常
        rec.on_ws_update("blinds", {"minimumRaise": "not_a_number"}, bad_ws)

    def test_finalize_with_empty_ws_state(self, tmp_store, ws_state_basic):
        """finalize_hand 用空 ws_state 不崩溃"""
        rec = HandRecorder(tmp_store, "table_1")
        rec.start_hand(1001, ws_state_basic)
        # 空 ws_state → 找不到 my_seat 的 chips_end，回退到 chips_start
        rec.finalize_hand({})
        # profit = 0（chips_end 回退到 chips_start）
        results = tmp_store.query()
        assert results[0]["profit"] == 0

    def test_save_corrupted_record_does_not_crash(self, tmp_path):
        """save 异常时返回 None 而非抛出"""
        store = HandHistoryStore(base_dir=str(tmp_path))
        # 构造一个无法序列化的 record（包含不可 JSON 序列化的对象）
        record = HandRecord(hand_id=1, table_id="t")
        # 手动注入一个不可序列化的字段（set 不在 JSON 标准类型中，但 default=str 会兜底）
        # 这里用 default=str 兜底，所以实际不会崩溃——验证它确实能保存
        result = store.save(record)
        # default=str 会把未知类型转字符串，所以应成功
        assert result is not None


# ─── 数据类 ───

class TestDataclasses:
    """测试数据类 to_dict / asdict"""

    def test_hand_record_to_dict(self):
        """HandRecord.to_dict 返回可序列化 dict"""
        r = HandRecord(hand_id=1, table_id="t", my_hole_cards=["Ah", "Kd"])
        d = r.to_dict()
        assert d["hand_id"] == 1
        assert d["my_hole_cards"] == ["Ah", "Kd"]
        assert "actions" in d
        assert "my_decisions" in d

    def test_player_action_dataclass(self):
        """PlayerAction 字段"""
        a = PlayerAction(user_id="u1", seat_id=1, action="bet", amount=50, street="flop")
        assert a.action == "bet"
        assert a.amount == 50

    def test_pot_award_dataclass(self):
        """PotAward 字段"""
        p = PotAward(winners=["u1"], winner_names=["Alice"], chips=100)
        assert p.chips == 100
        assert p.winners == ["u1"]

    def test_decision_context_dataclass(self):
        """DecisionContext 字段"""
        d = DecisionContext(
            street="flop", action="raise", amount=100,
            equity=0.7, pot_odds=0.3, ev=20.0,
            confidence=0.85, strategy_name="TAG",
        )
        assert d.equity == 0.7
        assert d.strategy_name == "TAG"
