"""
WebSocketListener 状态映射测试

覆盖 _update_players 中 raw_status → status 的映射：
- sitOut / sit_out → sit_out
- fold / folded → folded
- reserved / wait_list / waitList / queue → reserved (候补名单)
- playing / active / 其它 → active
"""
from unittest.mock import MagicMock

from src.platforms.browser.websocket_listener import WebSocketListener


def _make_listener():
    """构造一个最小可用的 listener（不启动 WS）"""
    mock_page = MagicMock()
    return WebSocketListener(page=mock_page)


def test_sit_out_mapped_to_sit_out():
    """WS 帧里 sitOut → sit_out"""
    listener = _make_listener()
    listener._update_players([
        {"seat": 1, "userId": "u1", "status": "sitOut", "stack": 0}
    ])
    assert listener.state["players"][1]["status"] == "sit_out"


def test_folded_mapped_to_folded():
    """WS 帧里 fold / folded → folded"""
    listener = _make_listener()
    listener._update_players([
        {"seat": 2, "userId": "u2", "status": "fold"}
    ])
    assert listener.state["players"][2]["status"] == "folded"

    listener._update_players([
        {"seat": 3, "userId": "u3", "status": "folded"}
    ])
    assert listener.state["players"][3]["status"] == "folded"


def test_reserved_state_not_mapped_to_active():
    """【关键修复】WS 帧里 state=reserved → reserved（不是 active！）"""
    listener = _make_listener()
    listener._update_players([
        {"seat": 4, "userId": "u1", "state": "reserved"}
    ])
    # 修复前：状态错认为 "active"
    # 修复后：状态正确为 "reserved"
    assert listener.state["players"][4]["status"] == "reserved", (
        f"reserved 应该映射为 'reserved'，实际是 "
        f"{listener.state['players'][4]['status']!r}"
    )


def test_wait_list_aliases_mapped_to_reserved():
    """wait_list / waitList / queue 都映射为 reserved"""
    listener = _make_listener()

    for raw in ("wait_list", "waitList", "queue"):
        listener._update_players([
            {"seat": 5, "userId": "u1", "state": raw}
        ])
        assert listener.state["players"][5]["status"] == "reserved", (
            f"{raw!r} 应该映射为 'reserved'"
        )


def test_playing_mapped_to_active():
    """playing 保持 active"""
    listener = _make_listener()
    listener._update_players([
        {"seat": 1, "userId": "u1", "status": "playing", "stack": 1000}
    ])
    assert listener.state["players"][1]["status"] == "active"


def test_field_name_fallback():
    """raw_status 从 status 字段读不到时，从 state 字段读"""
    listener = _make_listener()
    # 没 status 字段，只有 state
    listener._update_players([
        {"seat": 1, "userId": "u1", "state": "sitOut", "stack": 0}
    ])
    assert listener.state["players"][1]["status"] == "sit_out"


def test_reserved_then_playing_transition():
    """候补名单 → 实际入座 的状态转换"""
    listener = _make_listener()
    # 1. 初始：reserved
    listener._update_players([
        {"seat": 1, "userId": "u1", "state": "reserved"}
    ])
    assert listener.state["players"][1]["status"] == "reserved"
    # 2. 转正：playing
    listener._update_players([
        {"seat": 1, "userId": "u1", "status": "playing", "stack": 1000}
    ])
    assert listener.state["players"][1]["status"] == "active"
