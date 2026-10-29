# 跨智能体交接检查落地

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-25（Asia/Shanghai）
- 负责人 / 集成人：本次交接检查实施的 Codex 会话
- 用户目标及验收条件：提供跨工具可执行的接手摘要与交接检查；代码变更缺任务记录时能拦截；暂存检查不被未暂存内容蒙混；保留已有开发及发布流程。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点，新增内容尚未提交
- 本次负责的文件或模块：协作检查工具、Git hook、CI、发布脚本适配、相关测试与协作说明。

## 当前现场

- 已完成：标准库检查器、统一 Windows 入口、Git pre-commit 钩子及安装器、CI 配置、发布预检适配、模板和使用说明。
- 已启用：本仓库本机 hooksPath 指向 `D:/PM Stack/PM Stack/.githooks`，两个现有工作树均识别同一钩子；按实际 index 检查。研究工作树原有七个 spec 删除保持原状。
- 本轮验收范围：本机机制启用、回归与路径核对、CI 配置可评审；没有实际运行发布、构建 EXE 或修改远端仓库规则。
- 未完成：本轮验收范围无。远端 Actions 需本次文件提交推送后运行；若要禁止失败 PR 合并，还要由有权限者配置必需检查。
- 未提交修改与未跟踪文件：本任务 16 个仓库文件已准备，最终以 Git 状态及暂存检查核对；工作区外另更新入口、导航和转发 cmd，不随项目 Git 自动分发。
- 已提交但未共享的内容：本轮没有新提交或推送，HEAD 保持起点。

## 决策及原因

- 保留主项目唯一总索引；任务记录改为随实际代码分支提交，避免研究工作树代码与主工作树交接文档无法组成同一提交。
- staged 检查只读暂存区，CI 范围检查只读提交树；旧未修改记录不追溯。程序检查结构和范围，不代替测试或证明文档真实。
- 本机安装共用绝对 hook 路径，按实际提交目录检查；远端 CI 文件需提交推送后才生效，必需检查还要在仓库规则中启用。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-25（Asia/Shanghai）；`D:\PM Stack\PM Stack`；main / 7245d83cdc672636dcf344ee33319cf29a518957，代码为本次未提交变更。
- 命令：`.\.venv-review\Scripts\python.exe tools/run_tests.py tests.test_handoff_gate tests.test_publish_handoff --timeout 240`
- 结果：42 项，40 通过、2 跳过，退出码 0；日志 `.runtime-local/test-logs/tests-20261025-004808-669854.log`。
- 原因：两项符号链接回归因 Windows 缺少创建权限 WinError 1314 跳过；Linux CI 配置会执行这些测试，但远端尚未实际运行。
- 未提交被测代码：十个脚本/测试/自动化文件的 SHA-256 清单保存在 `.runtime-local/handoff-20261025/evidence.json`，清单摘要 `11c8df47aae0691098ef3da824ecaa1818eb37a3fe6389b95d5f0cc966b232ee`；此本机证据不随 Git 自动分发。
- 验证范围：临时 Git 仓库真实测试了缺记录拦截、完整记录放行、独立工作树 index、删除、重命名、未跟踪文件、旧记录不追溯、index/HEAD/工作区隔离；发布及网络操作采用模拟，无真实应用发布。
- 行尾与执行权限：`.gitattributes` 固定钩子为 LF，暂存时设置 pre-commit 的可执行位，避免 Windows 自动行尾转换破坏后续检出。
- 其他检查：PowerShell 安装器语法、`bash -n .githooks/pre-commit`、外层 cmd 的 status、主项目工作区检查、研究工作树 status、`publish.py --help` 均通过；发布 helper 在修改版本和构建前校验记录，精确暂存选定记录后检查 index。
- 验证局限：未运行完整应用回归或实际 GitHub Actions；检查只证明结构、范围和流程，不保证记录真实或模型理解正确。本地 hook 可以跳过，远端强制还依赖必需检查规则。

## 接手后的第一步

1. 本机流程与 CI 配置已按本轮范围完成，日常使用 `协作检查.cmd status`、`check` 和 `check --staged`。
2. 若用户授权启用远端流程，先提交推送本次准备的文件，确认 Actions 的 `handoff-check` 成功，再配置必需检查；不据此自动运行应用发布。
3. 其他 Agent 工具首次接入时，将项目规则指向 AGENTS.md 并核对读取结果；新机器重新安装本机 Git 钩子。

## 变更文件

- `.gitattributes`

- `tools/handoff.py`
- `tools/install_handoff_hook.ps1`
- `.githooks/pre-commit`
- `.github/workflows/handoff-check.yml`
- `协作检查.cmd`
- `tests/test_handoff_gate.py`
- `tests/test_publish_handoff.py`
- `publish.py`
- `发布新版本.bat`
- `AGENTS.md`
- `README.md`
- `CURRENT.md`
- `handoffs/TEMPLATE.md`
- `handoffs/README.md`
