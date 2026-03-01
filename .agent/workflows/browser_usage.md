---
description: 浏览器操作规范与状态持久化指引
---

# 浏览器操作规范

为了确保 Poker AI 的登录状态（Cookies、LocalStorage）能够持久化，并规避网站的安全检测，所有浏览器操作必须遵循以下规则：

## 1. 用户数据目录 (User Data Directory)
- **必须**使用项目根目录下的 `data/browser_data` 目录。
- 在使用 `playwright` 启动浏览器时，应使用 `launch_persistent_context`。

## 2. 自动化工具规范
- 当调用 `browser_subagent` 或其他浏览器自动化工具时，务必指明加载该物理路径。
- **严禁**创建空的或临时性的浏览器上下文进行测试，除非是为了验证纯净环境。

## 3. 登录与验证
- 所有的登录操作应手动或通过特定脚本在 `data/browser_data` 中完成。
- AI 运行期间，系统会自动读取该目录下的 Session 信息，不再要求重复登录。

## 4. 路径引用 (Absolute Path)
- 在脚本中引用该目录时，建议使用绝对路径或相对于项目根目录的可靠路径，确保在不同环境下运行的一致性。
