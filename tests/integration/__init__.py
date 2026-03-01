# tests/integration/__init__.py
"""
端到端集成测试（黑盒测试）。

这些测试从 main.py 入口启动，在真实浏览器中运行，通过监听浏览器状态和日志来验证系统行为。

运行方式：
    pytest tests/integration/ -v -s --tb=short

注意：
    - 需要有效的登录 session 在 data/browser_data/
    - 测试会操作真实浏览器，请在测试环境中运行
"""

import pytest

# 标记所有集成测试
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]
