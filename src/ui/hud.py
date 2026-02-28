import re

class HUD:
    def __init__(self):
        pass

    async def inject(self, page):
        """Injects the HUD HTML/CSS into the page."""
        if not page:
            return
        
        try:
            if page.is_closed():
                return
                
            # Check if already injected
            # Playwright eval can throw if page is closed/navigating, handled by try/except
            is_injected = await page.evaluate("() => !!document.getElementById('ai-hud')")
            if is_injected:
                return

            print("[HUD] 正在注入 AI 顾问界面...", flush=True)
            # Fixed JavaScript code - removed duplication that caused syntax error
            js_code = """() => {
                if (document.getElementById('ai-hud')) return;

                // Create wrapper for game content
                const gameWrapper = document.createElement('div');
                gameWrapper.id = 'ai-game-wrapper';
                gameWrapper.style.cssText = 'position: fixed; left: 0; top: 0; bottom: 0; right: 300px; overflow: auto; transition: right 0.3s ease;';
                
                // Move all body content into wrapper
                while (document.body.firstChild) {
                    gameWrapper.appendChild(document.body.firstChild);
                }
                document.body.appendChild(gameWrapper);
                
                // Create HUD sidebar
                const hud = document.createElement('div');
                hud.id = 'ai-hud';
                hud.style.cssText = 'position: fixed; top: 0; right: 0; bottom: 0; width: 300px; background: rgba(0,0,0,0.95); color: #0f0; font-family: monospace; font-size: 12px; overflow-y: auto; box-shadow: -4px 0 8px rgba(0,0,0,0.5); z-index: 2147483647; display: flex; flex-direction: column; transition: width 0.3s ease;';
                
                // Create resize handle
                const resizeHandle = document.createElement('div');
                resizeHandle.id = 'ai-resize-handle';
                resizeHandle.style.cssText = 'position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: #667eea; cursor: ew-resize; z-index: 10; transition: background 0.2s;';
                resizeHandle.onmouseenter = () => resizeHandle.style.background = '#764ba2';
                resizeHandle.onmouseleave = () => resizeHandle.style.background = '#667eea';
                
                hud.appendChild(resizeHandle);
                
                hud.innerHTML += `
                    <div id="ai-hud-header" style="padding: 12px; background: rgba(102, 126, 234, 0.2); border-bottom: 2px solid #667eea; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0;">
                        <span style="font-weight: bold; font-size: 14px;">AI 顾问 ✥</span>
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <button id="ai-mode-toggle" style="
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                color: white;
                                border: none;
                                padding: 6px 12px;
                                border-radius: 4px;
                                cursor: pointer;
                                font-weight: bold;
                                font-size: 10px;
                                transition: all 0.3s ease;
                            ">
                                模式: 辅助
                            </button>
                            <span id="ai-hud-close" style="cursor: pointer; color: #888; font-size: 20px; line-height: 1;">&times;</span>
                        </div>
                    </div>
                    <div id="ai-mode-status" style="padding: 6px 12px; background: rgba(102, 126, 234, 0.1); color: #888; font-size: 10px; border-bottom: 1px solid #555; flex-shrink: 0;">仅提供建议</div>
                    <div id="ai-hud-content" style="padding: 12px; color: #ddd; overflow-y: auto; flex: 1;">等待游戏状态...</div>
                `;
                
                document.body.appendChild(hud);
                
                // Resize functionality
                let isResizing = false;
                let startX = 0;
                let startWidth = 300;
                
                resizeHandle.addEventListener('mousedown', (e) => {
                    isResizing = true;
                    startX = e.clientX;
                    startWidth = parseInt(hud.style.width);
                    document.body.style.cursor = 'ew-resize';
                    e.preventDefault();
                });
                
                document.addEventListener('mousemove', (e) => {
                    if (isResizing) {
                        const diff = startX - e.clientX;
                        const newWidth = Math.max(250, Math.min(600, startWidth + diff));
                        hud.style.width = newWidth + 'px';
                        gameWrapper.style.right = newWidth + 'px';
                    }
                });
                
                document.addEventListener('mouseup', () => {
                    if (isResizing) {
                        isResizing = false;
                        document.body.style.cursor = '';
                    }
                });

                // Mode toggle functionality
                const toggleBtn = document.getElementById('ai-mode-toggle');
                const statusText = document.getElementById('ai-mode-status');
                let isAutoMode = false;
                
                if (toggleBtn) {
                    toggleBtn.onclick = () => {
                        isAutoMode = !isAutoMode;
                        if (isAutoMode) {
                            toggleBtn.textContent = '模式: 自动';
                            toggleBtn.style.background = 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)';
                            statusText.textContent = '自动执行操作';
                            statusText.style.color = '#f5576c';
                        } else {
                            toggleBtn.textContent = '模式: 辅助';
                            toggleBtn.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
                            statusText.textContent = '仅提供建议';
                            statusText.style.color = '#888';
                        }
                        window.dispatchEvent(new CustomEvent('ai-mode-change', { detail: { autoMode: isAutoMode } }));
                    };
                }

                // Close functionality
                const closeBtn = document.getElementById('ai-hud-close');
                if (closeBtn) {
                    closeBtn.onclick = () => {
                        hud.remove();
                        gameWrapper.style.right = '0';
                    };
                }
            }"""
            
            await page.evaluate(js_code)
            print("[HUD] 注入命令已发送。", flush=True)
        except Exception as e:
            print(f"[HUD] 注入失败: {e}", flush=True)
            pass



    async def update_content(self, page, decision_data):
        """Updates HUD with structured decision data including all players."""
        if not page or not decision_data:
            return
            
        try:
            if page.is_closed():
                return

            # Handle both old string format and new dict format for compatibility
            if isinstance(decision_data, str):
                # Old format - just display as before
                safe_suggestion = decision_data.replace("`", "").replace("${", "")
                formatted_html = self._format_legacy_content(safe_suggestion)
            else:
                # New structured format
                formatted_html = self._format_structured_content(decision_data)

            # Update content
            await page.evaluate(f"""() => {{
                const content = document.getElementById('ai-hud-content');
                if (content) {{
                    content.innerHTML = `{formatted_html}`;
                }}
            }}""")
        except Exception as e:
             # print(f"[HUD] Update failed: {e}", flush=True)
             pass

    def _format_structured_content(self, data: dict) -> str:
        """Formats structured decision data into HTML."""
        html_parts = []
        
        # My action and equity
        my_action = data.get("my_action", "").replace("`", "").replace("${", "")
        my_equity = data.get("my_equity", 0)
        my_hand_strength = data.get("my_hand_strength", "")
        
        # Header with my info
        html_parts.append(f"""
            <div style='margin-bottom: 12px; padding: 10px; background: rgba(102, 126, 234, 0.15); border-left: 4px solid #667eea; border-radius: 4px;'>
                <div style='color: #667eea; font-weight: bold; font-size: 0.9em; margin-bottom: 4px;'>你的建议</div>
                <div style='color: #fff; font-size: 1.1em;'>{my_action}</div>
                {f"<div style='color: #00ffff; font-weight: bold; margin-top: 6px;'>胜率: {my_equity:.1f}%</div>" if my_equity > 0 else ""}
            </div>
        """)
        
        # Players grid
        players = data.get("players", [])
        if players:
            html_parts.append("<div style='margin-top: 10px; border-top: 1px solid #555; padding-top: 10px;'>")
            html_parts.append("<div style='color: #888; font-size: 0.85em; margin-bottom: 8px;'>选手信息</div>")
            
            # Create grid of player cards (Single column)
            html_parts.append("<div style='display: grid; grid-template-columns: 1fr; gap: 8px;'>")
            
            for player in players:
                seat_id = player.get("seat_id", "?")
                status = player.get("status", "unknown")
                hand_range = player.get("hand_range", "未知")
                equity = player.get("equity", 0)
                chips = player.get("chips", 0)
                last_action = player.get("last_action", "无")
                is_active = player.get("is_active", False)
                
                # Color based on status
                if status == "folded" or not is_active:
                    bg_color = "rgba(100, 100, 100, 0.2)"
                    border_color = "#555"
                    text_color = "#666"
                else:
                    bg_color = "rgba(76, 175, 80, 0.15)"
                    border_color = "#4caf50"
                    text_color = "#ddd"
                
                # Player card
                html_parts.append(f"""
                    <div style='background: {bg_color}; border: 1px solid {border_color}; border-radius: 4px; padding: 6px; font-size: 0.75em;'>
                        <div style='color: {text_color}; font-weight: bold; margin-bottom: 3px;'>座位 {seat_id}</div>
                        <div style='color: #ff69b4; font-size: 0.85em; margin-top: 2px;'>{hand_range}</div>
                        {f"<div style='color: #00ffff; font-weight: bold; margin-top: 2px;'>{equity:.0f}%</div>" if equity > 0 and is_active else ""}
                    </div>
                """)
            
            html_parts.append("</div>")  # Close grid
            html_parts.append("</div>")  # Close players section
        
        return "".join(html_parts)

    def _format_legacy_content(self, suggestion: str) -> str:
        """Formats legacy string content (for backward compatibility)."""
        formatted_html = suggestion.replace("\n", "<br/>")
        
        # Highlight Win Rate / 胜率
        formatted_html = re.sub(
            r"(胜率[^<\n]*)",
            r"<div style='color: #00ffff; font-weight: bold; font-size: 1.3em; margin: 8px 0; padding: 5px; background: rgba(0,255,255,0.1); border-left: 3px solid #00ffff;'>\1</div>",
            formatted_html
        )
        
        # Highlight Actions
        formatted_html = re.sub(
            r"(过牌|弃牌|跟注|加注|全下)",
            r"<span style='color: #ffff00; font-weight: bold; font-size: 1.2em;'>\1</span>",
            formatted_html
        )
        
        return formatted_html
