# 正式版 v1.11.x 工作树现场

## 接手信息

- 状态：待确认。此文件保存已有工作的盘点，不代表本次新增功能任务或已验收结论。
- 盘点日期：2026-10-23（Asia/Shanghai）。
- 原执行者 / 集成人：待确认。
- 工作目录：`D:\PM Stack\PM Stack`。
- 分支：`main`。
- 盘点时 HEAD：`186c2dccf26a0e53375c8573690c7d5982d224fe`（v1.10.20 阶段成果）。
- 本地 README、应用入口及更新日志已声明 v1.11.5；这不证明已提交、打包或发布。
- 本轮只建立交接文档，不继续修改或验收以下功能。
- 2026-10-24：ZCode 会话按用户授权将下列全部未提交成果提交入库（提交 `9895c6b`，`main` 分支）；功能验收状态仍为待确认，本记录随之更新。

## 原有修改

盘点前已有 9 个已跟踪文件修改、19 个未跟踪文件；以下内容已于 2026-10-24 随提交 `9895c6b` 全部入库（`.gitignore` 与协作文档由后续提交处理）。接手时仍重新执行 `git status --short` 核对现场。

已跟踪文件修改：

- `README.md`、`软件更新日志.md`：版本与功能说明。
- `main.py`、`core/main_window.py`、`core/icons.py`：应用入口、导航及图标。
- `modules/product_matrix.py`：产品矩阵联动。
- `scripts/trend_by_attribute.py`：趋势曲线处理。
- `tests/test_clean_layout.py`：布局相关回归。
- `tools/build_review_fix.ps1`：构建入口。

未跟踪文件：

- `modules/display_dashboard.py`。
- `core/dashboard_combo.py`、`core/dashboard_data.py`、`core/dashboard_filters.py`、`core/dashboard_import.py`、`core/dashboard_research_check.py`、`core/dashboard_smoke.py`、`core/dashboard_widgets.py`。
- `tests/test_dashboard.py`、`tests/test_dashboard_import.py`、`tests/test_dashboard_chart.py`、`tests/test_trend_curves.py`。
- `PM Stack v1.11.0.spec` 至 `PM Stack v1.11.5.spec`，共 6 份。
- `展示看板使用说明.md`。

当前内容涉及第五个“展示看板”模块、数据导入/筛选/统计/导出、产品矩阵联动及交叉属性趋势平滑。具体完成度和原始验收要求需向当前用户任务及原执行记录核对，不能仅凭文件存在认定完成。

## 历史验证证据

以下为现存日志的结果摘录，本次没有重新运行测试。文件名中的时间未独立核验时区；日志目录为 `.runtime-local/test-logs/`，不随源码分发。

| 日志文件 | 记录结果 | 可确认的范围 |
|---|---|---|
| `tests-20261022-151912-756773.log` | 263 项，OK | 覆盖多个模块的历史测试 |
| `tests-20261022-170000-673952.log` | 40 项，OK | 看板、导入、图表及布局相关历史测试 |
| `tests-20261022-174129-531188.log` | 17 项，FAILED：1 failure、1 error | 包含密钥保护 / 旧明文密钥迁移失败；涉及 DPAPI 调用异常 |
| `tests-20261022-174210-733046.log` | 17 项，OK | 3 项趋势曲线与 14 项 hotfix 历史测试 |
| `tests-20261024-145650-814187.log` | 43 项，OK | 2026-10-24 提交 `9895c6b` 后即时运行：`.venv-review` 解释器执行 `tools/run_tests.py tests.test_dashboard tests.test_dashboard_import tests.test_dashboard_chart tests.test_trend_curves tests.test_clean_layout --timeout 240`，被测代码即提交现场（工作树无额外改动） |

- 这些日志未记录完整命令、解释器环境及被测代码指纹，无法据此确认当前工作树全量通过。
- 两次 17 项执行结果不同，环境差异及恢复原因待确认；不能仅凭后一次成功声称根因已解决。
- README 的 230 项属于 v1.10.20 的历史结果，不是本工作树当前基线。
- 本轮没有核验 EXE、真实工作簿自检、打包结果或远端发布状态。

## 接手后的第一步

仅在本次用户任务需要继续或交付这些修改时：

1. 在上述工作目录核对分支、HEAD、`git status --short` 和相关 diff，确认未跟踪文件仍在。不要通过重新检出 HEAD 代替保留当前现场。
2. 明确本次目标、验收条件及负责人；将展示看板、趋势曲线是否一起交付记录清楚，不默认所有本地文件属于同一任务。
3. 若验证看板和趋势修改，可先执行以下相关回归；本记录只提供命令，未执行：

   ```powershell
   .\.venv-review\Scripts\python.exe tools/run_tests.py tests.test_dashboard tests.test_dashboard_import tests.test_dashboard_chart tests.test_trend_curves tests.test_clean_layout --timeout 240
   ```

4. 公共改动集成或发布前执行完整回归，记录当时的代码现场和环境；若密钥相关测试失败，保留结果并辨别环境原因。
5. 如需跨工作树或异机接手，先形成可恢复的代码提交或变更快照；当前未提交文件只存在于本工作树。

## 本次协作文件变更

2026-10-23 新增 `CURRENT.md`、交接模板及两份现场记录，补充 `AGENTS.md` 的入口，并取消对 `AGENTS.md` 的 Git 忽略。工作区上级另有本机入口 `D:\PM Stack\AGENTS.md`。本次不替既有功能作验收结论。

2026-10-24：ZCode 会话按用户授权将 v1.11.x 全部未提交修改与未跟踪文件提交为 `9895c6b`（28 个文件，+3806 行），提交后相关回归 43 项通过（日志见上表）。协作协议、任务索引、交接记录、`.gitignore` 调整及《产品信息提取改进方案》随后另行提交；均未推送到远端，研究工作树未做任何改动。
