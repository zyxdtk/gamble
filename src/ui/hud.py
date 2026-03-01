import re

class HUD:
    def __init__(self):
        pass

    async def inject(self, page):
        """No longer injects into DOM. Handled strictly via terminal for automation stability."""
        pass



    async def update_content(self, page, decision_data):
        """Outputs HUD decisions cleanly to the terminal."""
        if not decision_data or not decision_data.get("decision"):
            return
            
        print("\n================= [AI 决策屏] =================", flush=True)
        if isinstance(decision_data, str):
            print(f"-> 建议: {decision_data}", flush=True)
        else:
            decision_obj = decision_data.get("decision", {})
            action = decision_obj.get("action", "")
            amount = decision_obj.get("amount", "")
            my_str = decision_data.get("my_hand_strength", "")
            my_eq = decision_data.get("my_equity", 0)
            
            print(f"-> 强度: {my_str}", flush=True)
            print(f"-> 动作: {action}" + (f" (金额: {amount})" if amount else ""), flush=True)
            if my_eq > 0:
                print(f"-> 胜率: {my_eq:.1f}%", flush=True)
            
            players = decision_data.get("players", [])
            if players:
                print("--------- 对手信息 ---------", flush=True)
                for p in players:
                    seat_id = p.get("seat_id", "?")
                    status = "✅" if p.get("is_active", False) and p.get("status") != "folded" else "😴"
                    rng = p.get("hand_range", "未知")
                    print(f" 座位 {seat_id} {status} | 范围: {rng}", flush=True)
        print("====================================================\n", flush=True)

