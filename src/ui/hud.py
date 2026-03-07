import re

class HUD:
    def __init__(self):
        pass

    async def inject(self, page):
        """No longer injects into DOM. Handled strictly via terminal for automation stability."""
        pass



    async def update_content(self, page, decision_data):
        """Outputs HUD decisions cleanly to the terminal."""
        if not decision_data or not isinstance(decision_data, dict):
            return
            
        print("\n================= [AI 决策屏] =================", flush=True)
        status = decision_data.get("status", "READY")
        if status == "WAITING":
            print("-> 状态: ⏳ 等待发牌中...", flush=True)
        else:
            action = decision_data.get("action", "")
            amount = decision_data.get("amount", 0)
            reasoning = decision_data.get("my_hand_strength", "")
            my_eq = decision_data.get("my_equity", 0)
            
            print(f"-> 强度: {reasoning}", flush=True)
            print(f"-> 动作: {action}" + (f" (金额: {amount})" if amount else ""), flush=True)
            if my_eq > 0:
                print(f"-> 胜率: {my_eq:.1f}%", flush=True)
        
        # 显示网页端当前可用的选项 (不论状态)
        available = decision_data.get("available_actions", [])
        if available:
            print(f"-> 可选: [{', '.join(available)}]", flush=True)
        
        players = decision_data.get("players", [])
        if players:
            print("--------- 对手信息 ---------", flush=True)
            for p in players:
                seat_id = p.get("seat_id", "?")
                status_icon = "✅" if p.get("is_active", False) and p.get("status") != "folded" else "😴"
                rng = p.get("hand_range", "未知")
                print(f" 座位 {seat_id} {status_icon} | 范围: {rng}", flush=True)
        print("====================================================\n", flush=True)
