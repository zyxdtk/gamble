#!/usr/bin/env python3
"""
手牌复盘脚本

读取 data/hand_history/ 下的 JSONL 文件，结构化输出每手牌的回放：
- 头注/盲注/座位
- 翻前/翻牌/转牌/河牌 各街道行动
- 我方决策（含 equity/ev/reasoning）
- 底池颁奖 + 盈亏

用法：
    uv run python scripts/replay_hand.py                       # 列出最近 10 手摘要
    uv run python scripts/replay_hand.py --hand-id 1395659845  # 复盘单手
    uv run python scripts/replay_hand.py --date 2026-06-28     # 某日全部
    uv run python scripts/replay_hand.py --table 16985618       # 某桌全部
    uv run python scripts/replay_hand.py --stats               # 统计摘要
    uv run python scripts/replay_hand.py --limit 50            # 最近 50 手
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional


# ─── 路径与常量 ─────────────────────────────────────────────────────────────

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "hand_history",
)

STREET_ORDER = ["preflop", "flop", "turn", "river"]
ACTION_EMOJI = {
    "fold": "❌",
    "check": "✓",
    "call": "📞",
    "bet": "💰",
    "raise": "⬆️",
    "all_in": "🔥",
}

# 位置顺序（5 人桌参考）
POSITION_NAMES = {
    0: "SB", 1: "BB", 2: "UTG", 3: "MP/HJ", 4: "CO", 5: "BTN",
}


# ─── 加载 ─────────────────────────────────────────────────────────────────

def load_hands(
    data_dir: str = DEFAULT_DATA_DIR,
    hand_id: Optional[int] = None,
    date: Optional[str] = None,
    table_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """读取并筛选手牌记录"""
    if not os.path.isdir(data_dir):
        return []

    pattern = os.path.join(data_dir, "hands_*.jsonl")
    files = sorted(glob.glob(pattern))
    if date:
        # date 形如 2026-06-28
        date_compact = date.replace("-", "")
        files = [f for f in files if date_compact in os.path.basename(f)]

    hands: List[Dict[str, Any]] = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if hand_id is not None and rec.get("hand_id") != hand_id:
                        continue
                    if table_id is not None and rec.get("table_id") != table_id:
                        continue
                    rec["_source_file"] = os.path.basename(fp)
                    hands.append(rec)
        except OSError:
            continue

    # 按时序倒序
    hands.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return hands


# ─── 格式化辅助 ───────────────────────────────────────────────────────────

def fmt_cards(cards: List[str]) -> str:
    """格式化扑克牌：['9h', 'Jh'] → '9h Jh'"""
    return " ".join(cards) if cards else "-"


def fmt_money(n: int, bb: int = 0) -> str:
    """筹码 + BB 标注"""
    if bb > 0:
        return f"{n:+d} ({n / bb:+.1f}BB)"
    return f"{n:+d}"


def infer_position(hand: Dict[str, Any]) -> str:
    """根据 dealer_seat 和 my_seat 推断我的位置

    简化逻辑：从 dealer 顺时针数 my_seat 是第几个活跃座位
    """
    dealer = hand.get("dealer_seat")
    my_seat = hand.get("my_seat")
    if dealer is None or my_seat is None:
        return "?"

    # 收集活跃座位（players dict 的 key）
    seats = []
    for k in hand.get("players", {}).keys():
        try:
            seats.append(int(k))
        except (ValueError, TypeError):
            continue
    seats = sorted(seats)
    if not seats or my_seat not in seats:
        return "?"

    # dealer 索引
    try:
        dealer_idx = seats.index(dealer)
        my_idx = seats.index(my_seat)
    except ValueError:
        return "?"

    n = len(seats)
    # 顺时针距离（0=自己是 dealer）
    dist = (my_idx - dealer_idx) % n

    # 简化：5 人桌用 dist 映射
    if n == 2:
        return "BTN" if dist == 0 else "BB"
    if n == 3:
        return ["BTN", "SB", "BB"][dist]
    if n <= 6:
        # 0=BTN, 1=SB, 2=BB, 3=UTG, 4=MP/HJ, 5=CO
        labels_6 = ["BTN", "SB", "BB", "UTG", "MP/HJ", "CO"]
        # 5 人桌：0=BTN, 1=SB, 2=BB, 3=UTG, 4=CO
        labels_5 = ["BTN", "SB", "BB", "UTG", "CO"]
        if n == 5:
            return labels_5[dist]
        return labels_6[dist]
    # 多人桌：粗粒度
    return f"pos{dist}"


def community_for_street(hand: Dict[str, Any], street: str) -> List[str]:
    """取某街道的公牌"""
    if street == "preflop":
        return []
    by_street = hand.get("community_cards_by_street", {}) or {}
    if street in by_street and by_street[street]:
        return by_street[street]
    # fallback：community_cards_final 可能未更新
    final = hand.get("community_cards_final", []) or []
    if street == "flop":
        return final[:3] if len(final) >= 3 else final
    if street == "turn":
        return final[:4] if len(final) >= 4 else final
    if street == "river":
        return final[:5] if len(final) >= 5 else final
    return []


# ─── 单手复盘 ─────────────────────────────────────────────────────────────

def classify_actions_by_amount(actions: List[Dict[str, Any]], big_blind: int) -> List[Dict[str, Any]]:
    """对已记录的动作做 best-effort 重新分类（仅用于显示）

    历史 JSONL 数据可能把 raise 错记成 call，丢失了 raiseTo 字段。
    通过对比 amount 与当前街道的最大下注推断：
    - 如果本动作的 amount 等于当前最大下注：call
    - 如果本动作的 amount > 当前最大下注：raise
    - fold / check 不变

    按街道分别处理：每个街道开始时最大下注从 BB 重置。
    新记录的数据会保留 raiseTo 字段，本函数对其无影响。
    """
    by_street: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in actions:
        by_street[a.get("street", "preflop")].append(a)

    fixed: List[Dict[str, Any]] = []
    for street in STREET_ORDER:
        street_actions = by_street.get(street, [])
        if not street_actions:
            continue
        # 每个街道开始时最大下注 = BB（preflop 是 BB；翻后从 0 起，新 bet 才抬高）
        current_max = big_blind if street == "preflop" else 0
        for a in street_actions:
            new_a = dict(a)
            action = a.get("action", "")
            amount = a.get("amount", 0) or 0
            if action == "call" and amount > current_max and amount > 0:
                # 翻后从 0 起，amount > 0 就是 bet；翻前 amount > BB 是 raise
                if street == "preflop":
                    new_a["action"] = "raise"
                else:
                    new_a["action"] = "bet"
            # 更新 current_max
            if new_a.get("action") in ("raise", "bet"):
                current_max = max(current_max, amount)
            fixed.append(new_a)
    return fixed


def render_hand(hand: Dict[str, Any], verbose: bool = True) -> str:
    """格式化输出单手牌"""
    out: List[str] = []

    hand_id = hand.get("hand_id", "?")
    table_id = hand.get("table_id", "?")
    ts = hand.get("timestamp", "?")
    bb = hand.get("big_blind", 0)
    my_seat = hand.get("my_seat")
    hole = hand.get("my_hole_cards", []) or []
    pos = infer_position(hand)

    # ── 头部 ──
    out.append("=" * 70)
    out.append(f"🃏 手牌 #{hand_id}    桌 {table_id}    {ts}")
    out.append(f"   盲注 {bb}    我: seat {my_seat} ({pos})    底牌: {fmt_cards(hole)}")
    out.append("=" * 70)

    # ── 玩家初始筹码 ──
    players = hand.get("players", {}) or {}
    out.append("\n📊 玩家筹码")
    for seat_key in sorted(players.keys(), key=lambda x: int(x) if str(x).isdigit() else 999):
        p = players[seat_key]
        seat_id = p.get("seat_id", seat_key)
        name = p.get("name") or f"seat{seat_id}"
        is_me = " 👈" if seat_id == my_seat else ""
        delta = p.get("chips_end", 0) - p.get("chips_start", 0)
        out.append(
            f"   seat {seat_id:>2}  {name:<14}  "
            f"{p.get('chips_start', 0):>5} → {p.get('chips_end', 0):>5}  "
            f"({delta:+d}){is_me}"
        )

    # ── 按街道分组动作（先做 best-effort 重新分类）──
    bb = hand.get("big_blind", 0)
    actions = classify_actions_by_amount(
        hand.get("actions", []) or [], bb
    )
    by_street: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in actions:
        by_street[a.get("street", "preflop")].append(a)

    out.append("\n🎬 行动回放")
    for street in STREET_ORDER:
        street_actions = by_street.get(street, [])
        if not street_actions:
            continue

        # 街道标题（含公牌）
        if street == "preflop":
            out.append("\n  ── Preflop ──")
        else:
            board = community_for_street(hand, street)
            out.append(f"\n  ── {street.capitalize()} ── 公牌: {fmt_cards(board)}")

        for a in street_actions:
            seat = a.get("seat_id", "?")
            action = a.get("action", "?")
            amount = a.get("amount", 0)
            time = a.get("timestamp", "")[11:19]  # HH:MM:SS
            emoji = ACTION_EMOJI.get(action, "·")
            mark = " 👈" if seat == my_seat else ""
            amount_str = f" {amount}" if amount else ""
            out.append(f"   {time}  seat {seat}{mark}  {emoji} {action}{amount_str}")

    # ── 我方决策 ──
    my_decisions = hand.get("my_decisions", []) or []
    if my_decisions:
        out.append("\n🧠 我方决策")
        for d in my_decisions:
            street = d.get("street", "?")
            action = d.get("action", "?")
            amount = d.get("amount", 0)
            equity = d.get("equity", 0.0) or 0.0
            pot_odds = d.get("pot_odds", 0.0) or 0.0
            ev = d.get("ev", 0.0) or 0.0
            strat = d.get("strategy_name", "")
            reasoning = d.get("reasoning", "")
            time = d.get("timestamp", "")[11:19]
            amount_str = f" {amount}" if amount else ""
            extra = ""
            if equity:
                extra += f" Eq:{equity:.0%}"
            if pot_odds:
                extra += f" PO:{pot_odds:.0%}"
            if ev:
                extra += f" EV:{ev:+.1f}"
            out.append(
                f"   {time}  {street:<8}  {action}{amount_str}  "
                f"[{strat}]{extra}"
            )
            if verbose and reasoning:
                out.append(f"              └ {reasoning}")

    # ── 底池颁奖 ──
    awards = hand.get("pot_awards", []) or []
    if awards:
        out.append("\n🏆 底池颁奖")
        for aw in awards:
            winners = aw.get("winner_names", []) or aw.get("winners", [])
            chips = aw.get("chips", 0)
            winners_str = ", ".join(winners) if winners else "?"
            out.append(f"   {chips} → {winners_str}")

    # ── 结果 ──
    profit = hand.get("my_profit", 0)
    chips_start = hand.get("chips_start", 0)
    chips_end = hand.get("chips_end", 0)
    out.append("\n" + "─" * 70)
    emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
    out.append(
        f"{emoji} 结果:  {chips_start} → {chips_end}  "
        f"(净 {fmt_money(profit, bb)})"
    )
    out.append("─" * 70)
    return "\n".join(out)


def render_summary_line(hand: Dict[str, Any]) -> str:
    """单行摘要：hand_id  时间  位置  底牌  盈亏"""
    hand_id = hand.get("hand_id", "?")
    ts = hand.get("timestamp", "")[11:19]
    pos = infer_position(hand)
    hole = fmt_cards(hand.get("my_hole_cards", []) or [])
    profit = hand.get("my_profit", 0)
    bb = hand.get("big_blind", 0)
    emoji = "🟢" if profit > 0 else ("🔴" if profit < 0 else "⚪")
    return (
        f"  #{hand_id:<12}  {ts}  {pos:<7}  {hole:<10}  "
        f"{emoji} {fmt_money(profit, bb)}"
    )


# ─── 统计 ─────────────────────────────────────────────────────────────────

def compute_stats(hands: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统计聚合指标"""
    if not hands:
        return {}

    total = len(hands)
    profits = [h.get("my_profit", 0) for h in hands]
    bb_values = [h.get("big_blind", 1) for h in hands]
    profit_bb = [p / b if b else 0 for p, b in zip(profits, bb_values)]

    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    evens = sum(1 for p in profits if p == 0)

    actions_by_street: Dict[str, Counter] = defaultdict(Counter)
    for h in hands:
        bb_h = h.get("big_blind", 1)
        fixed_actions = classify_actions_by_amount(
            h.get("actions", []) or [], bb_h
        )
        for a in fixed_actions:
            seat = a.get("seat_id")
            if seat == h.get("my_seat"):
                actions_by_street[a.get("street", "?")][a.get("action", "?")] += 1

    # 按街道的 hero 决策分布
    hero_decisions: Dict[str, Counter] = defaultdict(Counter)
    for h in hands:
        for d in h.get("my_decisions", []) or []:
            hero_decisions[d.get("street", "?")][d.get("action", "?")] += 1

    # 翻前 VPIP/PFR（我方是否主动入池 / 加注）
    vpip_hands = 0
    pfr_hands = 0
    for h in hands:
        my_seat = h.get("my_seat")
        bb_h = h.get("big_blind", 1)
        fixed_actions = classify_actions_by_amount(
            h.get("actions", []) or [], bb_h
        )
        preflop = [a for a in fixed_actions
                   if a.get("street") == "preflop" and a.get("seat_id") == my_seat]
        # VPIP: 主动 call/raise 入池（排除 BB 免费过牌）
        if any(a.get("action") in ("call", "bet", "raise") for a in preflop):
            # 如果是 BB 位置且只有 check（无 call），不算 VPIP
            if not (infer_position(h) == "BB" and all(a.get("action") == "check" for a in preflop)):
                vpip_hands += 1
        if any(a.get("action") == "raise" for a in preflop):
            pfr_hands += 1

    return {
        "total_hands": total,
        "wins": wins,
        "losses": losses,
        "evens": evens,
        "win_rate": wins / total * 100 if total else 0,
        "total_profit": sum(profits),
        "total_profit_bb": sum(profit_bb),
        "avg_profit_bb": sum(profit_bb) / total if total else 0,
        "best_hand_bb": max(profit_bb) if profit_bb else 0,
        "worst_hand_bb": min(profit_bb) if profit_bb else 0,
        "vpip": vpip_hands / total * 100 if total else 0,
        "pfr": pfr_hands / total * 100 if total else 0,
        "hero_actions_by_street": {s: dict(c) for s, c in actions_by_street.items()},
        "hero_decisions_by_street": {s: dict(c) for s, c in hero_decisions.items()},
    }


def render_stats(stats: Dict[str, Any]) -> str:
    out: List[str] = []
    out.append("=" * 70)
    out.append("📈 统计摘要")
    out.append("=" * 70)
    out.append(f"  总手数:        {stats['total_hands']}")
    out.append(f"  胜/负/平:      {stats['wins']} / {stats['losses']} / {stats['evens']}")
    out.append(f"  胜率:          {stats['win_rate']:.1f}%")
    out.append(f"  总盈亏:        {stats['total_profit']:+d} ({stats['total_profit_bb']:+.1f} BB)")
    out.append(f"  平均盈亏:      {stats['avg_profit_bb']:+.2f} BB/手")
    out.append(f"  最好/最差:     {stats['best_hand_bb']:+.1f} / {stats['worst_hand_bb']:+.1f} BB")
    out.append(f"  VPIP:          {stats['vpip']:.1f}%")
    out.append(f"  PFR:           {stats['pfr']:.1f}%")
    out.append("")
    out.append("  我方动作（按街道）:")
    for street in STREET_ORDER:
        if street in stats["hero_actions_by_street"]:
            acts = stats["hero_actions_by_street"][street]
            acts_str = ", ".join(f"{k}={v}" for k, v in sorted(acts.items()))
            out.append(f"    {street:<10}  {acts_str}")
    out.append("=" * 70)
    return "\n".join(out)


# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="手牌复盘：读取 data/hand_history/ 下的 JSONL 记录",
    )
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help=f"hand_history 目录（默认: {DEFAULT_DATA_DIR}）")
    parser.add_argument("--hand-id", type=int, help="复盘指定 hand_id")
    parser.add_argument("--date", help="指定日期（YYYY-MM-DD）")
    parser.add_argument("--table", help="指定 table_id")
    parser.add_argument("--limit", type=int, default=10,
                        help="最近多少手（默认 10）")
    parser.add_argument("--stats", action="store_true", help="显示统计摘要")
    parser.add_argument("--quiet", action="store_true",
                        help="只显示每手一行摘要（用于浏览多手）")
    parser.add_argument("--no-reasoning", action="store_true",
                        help="决策不展开 reasoning")
    args = parser.parse_args()

    hands = load_hands(
        data_dir=args.data_dir,
        hand_id=args.hand_id,
        date=args.date,
        table_id=args.table,
    )

    if not hands:
        print(f"❌ 没有匹配的手牌（data_dir={args.data_dir}）", file=sys.stderr)
        sys.exit(1)

    # 单手复盘模式
    if args.hand_id is not None:
        print(render_hand(hands[0], verbose=not args.no_reasoning))
        return

    # 统计模式
    if args.stats:
        # 统计 = 全量，不受 limit 影响
        all_hands = load_hands(
            data_dir=args.data_dir,
            date=args.date,
            table_id=args.table,
        )
        stats = compute_stats(all_hands)
        if not stats:
            print("❌ 无可统计数据", file=sys.stderr)
            sys.exit(1)
        print(render_stats(stats))
        return

    # 列表模式
    shown = hands[:args.limit]
    print(f"📋 找到 {len(hands)} 手，显示最近 {len(shown)} 手：\n")
    if args.quiet:
        for h in shown:
            print(render_summary_line(h))
    else:
        for h in shown:
            print(render_hand(h, verbose=not args.no_reasoning))
            print()


if __name__ == "__main__":
    main()
