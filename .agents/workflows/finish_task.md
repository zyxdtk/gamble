---
description: Standard procedure to finalize a task, update the changelog, and push to GitHub.
---

# 任务完成与代码提交流程 (Finish Task Workflow)

当一个特定的开发任务或修复完成时，请严格按照以下步骤进行收尾：

## 1. 更新更新历史 (Changelog)
首先，根据刚刚完成的工作，在 `docs/changelog.md` 的最上方新增一条今天的日期记录，并简明扼要地列出改动点。

## 2. 检查代码状态
确认所有的测试通过，并且没有未解决的语法错误。

// turbo
```bash
git status
```

## 3. 提交与推送 (Commit & Push)
将所有改动加入暂存区，编写有意义的 Commit Message，然后推送到远端 (GitHub)。

> 注意：因为使用的是 SSH 配置，可以直接 push。

// turbo
```bash
git add .
git commit -m "chore: $(date '+%Y-%m-%d') updates"
git push origin main
```
