# 2026-10-28：审查修复第一批——文件保护与类目失败续跑

## 接手信息

- 状态：待确认
- 更新日期与时区：2026-10-28（Asia/Shanghai）
- 负责人 / 集成人：用户保存的 PM Stack 修复助手（本实施会话）负责实施与自验；Qoder 主会话负责索引、差异复核与集成验收（复核尚未进行）。
- 用户目标及验收条件：按两份审查报告逐批修复；本批限定 A 报告 R01/R02/R06。输入原件不被中间保存或结果导出覆盖；输出安全落盘；失败状态与业务结论分离；续跑只补未完成项；以合成数据与假模型完成回归。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点，本批不提交故 HEAD 未变
- 本次负责的文件或模块：类目筛选脚本及其 UI 入口、销额矩阵2导出及其 UI 入口、新增小型安全输出工具 core/report_io.py 及三份定向测试；精确路径见「变更文件」，逐文件要点见「变更说明」。
- 公共文件协调 / 依赖任务：本会话是本批唯一源码写入者。开工时发现旧实施会话 4cd7f9d5 仍在并发写同批文件，经 AskUserQuestion 由用户选择「停止旧会话，由本会话接手」，遂停止该会话、保留其已落盘成果后核对与补强，不重复建档、不重置现场。CURRENT.md 由主会话独占维护，本记录不改总索引。保留字段归一化等既有未提交修改。不操作研究工作树，不修改 runner/main_window 等下一批范围。
- 交付方式：同工作树串行实施与复核，不暂存、不提交、不推送、不打包、不发布。

## 当前现场

- 已完成：核实专用 Agent 就绪并停止冲突旧会话；读取规则、报告、脚本入口；保存修改前源码副本、151 文件基线指纹及暂存/未暂存差异；核对并补强 R01/R02/R06 修复；新增定向隔离回归并跑通既有相关回归；磁盘上另存有合并定向 76 项与全量 405 项通过日志（见「验证证据」）。
- 未完成 / 已知问题：主会话独立差异复核尚未进行（本记录状态为待确认，下一步即交主会话复核）；实屏 GUI 手动操作、真实模型 API、真实采集、正式业务数据与发布 EXE 均未验证（未授权）；R03 金额字符串 coerce 丢失与重复 ASIN 关联放大、R04 机会得分固定分析日期、R05 关窗不等 daemon 保存、R07 至 R11 均不在本批范围。
- 未提交修改与未跟踪文件：开工既有变更全部保留；本批新增 core/report_io.py 与 3 份测试为未跟踪，修改 4 个授权源码为未暂存；均不暂存、不提交。
- 已提交但未共享的内容：本批无提交。
- 恢复位置：.runtime-local/review-fixes-20261028-batch1/ 下 baseline-*（只读开工依据）、before/（原始源码副本）、takeover/ 与 takeover-*（接手时快照与差异）、final-batch-sha256.json（本会话核实的本批 8 文件最终指纹）、final-sha256.json、final-worktree-verification.json、main-review-sha256.json、after/（8 文件修复后副本）、final-targeted.log、final-related-regression.log、resume-final-tests.log。这些是复核依据，不授权恢复或重置现场。

## 决策及原因

- 2026-10-28：用户已保存 PM Stack 修复助手；接口确认 Agent 就绪。接口不提供友好模型名映射，实施者不凭名称自报或推断所用模型，按实际保存配置运行。
- 2026-10-28：开工发现旧会话 4cd7f9d5 仍在写同批文件，与「唯一源码写入者」前提冲突；经用户选择停止旧会话由本会话接手，保留其已落盘成果后核对补强，不重启新会话、不转派默认 Agent、不清理现场。
- 2026-10-28：主项目带未提交成果，本任务同工作树串行写入，避免新 worktree 遗漏未提交成果；实施期间不并行其他源码修改。
- 2026-10-28：先修 R01/R02/R06；矩阵金额/重复键（R03）与机会日期（R04）留第二批，关闭生命周期（R05）留后续批次，避免混合改动。
- 2026-10-28：类目输入恒只读，默认在输入旁另存 `原名_类目筛选结果.xlsx`；断点独立为原子 JSON 存于任务状态目录（LOCALAPPDATA/PM Stack/tasks/category-screening，可经 CATEGORY_STATE_DIR 覆写），绑定「源路径 + 源内容 SHA-256 + 有效参数指纹（模型/base_url/画像/prompt 版本/温度/max_tokens/批大小）+ schema 版本」；同源同参才续跑，源内容、行顺序、模型或画像变化按 binding 与行指纹失效重评；断点按原始 row_index 存，结果表排序仅影响展示，不改变断点行身份；结果文件再作输入可按行状态续跑。
- 2026-10-28：失败与业务结论分离——新增「处理状态」（成功/可重试失败/待人工审核/人工确认/待处理）与「错误原因」列；只跳过真实成功与人工确认行，可重试失败与待人工审核会重评；模型失败不写「人工审核」冒充完成；非法评分/枚举/越界/重复 row_index/超大整数/超长文本/非法 XML 字符判为该行失败并保留其余合法行；旧表无状态列时不把历史「人工审核」当成功，且不覆盖人工确认数据。
- 2026-10-28：所有输出/断点经同目录临时文件、完整校验后原子替换（JSON 往返一致；Excel 逐 ZIP/XML、行列数、列名与逐单元格内容比对，含 32767 文本上限与公式注入防护）；Windows 短暂 PermissionError 有界退避重试（4 次），最终失败保留旧目标并给出可恢复临时件位置；类目停止走协作停止文件与 KeyboardInterrupt，保存后退出，不改全局 runner 与关窗（后批），不声称已修复强杀进程的全局关闭问题。矩阵2 UI 与 CLI 双层拒绝输入=输出（含默认输出落到输入、大小写/相对/规范化/硬链接别名），写入前校验，不改 150/177/303 附近金额与重复键统计逻辑，不改其他矩阵类型。
- 2026-10-28：不修改脏的 core/field_workbook.py，另建小型 core/report_io.py 承载路径归一、同源判定与安全落盘，供类目与矩阵共用，减少与既有未提交改动的冲突面。
- 2026-10-28：测试读取日志改为 `log3.text.toPlainText()`，不给公共控件 LogConsole 增加接口，避免为凑断言扩大公共范围。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-28 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 命令：定向回归 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_category_screening tests.test_product_matrix2 tests.test_report_io --timeout 240`；相关回归 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_task_interaction tests.test_task_button_signals tests.test_field_templates tests.test_field_row_filter tests.test_field_workbook tests.test_field_resume tests.test_field_normalization tests.test_product_matrix3 tests.test_matrix_workspace --timeout 240`；UI 基线 `... tests.test_task_interaction tests.test_task_button_signals --timeout 240`；合并定向与全量见磁盘日志；协作检查 `python tools/handoff.py status --repo "D:/PM Stack/PM Stack"` 与 `python tools/handoff.py check --repo "D:/PM Stack/PM Stack"`。全部经 tools/run_tests.py 子进程隔离入口，QT_QPA_PLATFORM=offscreen，未开正式应用。
- 结果：本会话定向回归 Ran 61 OK 0 fail/0 error/0 skip（tests-20261028-140432-486435.log，副本 final-targeted.log）；本会话相关回归 Ran 87 OK 0 fail/0 error/0 skip（tests-20261028-140442-925914.log，副本 final-related-regression.log）；接手 UI 基线 Ran 15 OK（takeover-ui-baseline.log）。磁盘另存合并定向 Ran 76 OK（tests-20261028-140448-217521.log、tests-20261028-140727-766914.log，副本 resume-final-tests.log）与全量 Ran 405 OK skipped=2（tests-20261028-140812-593247.log），skipped=2 为历史已知 Windows 符号链接权限限制；上述日志均针对同一最终 8 文件状态（final-sha256.json 与 main-review-sha256.json 逐项一致）。handoff check 结果见「收工检查」。
- 用例分布：本会话定向 61 = test_category_screening 36 + test_product_matrix2 14 + test_report_io 11；本会话相关回归 87 = test_field_normalization 24 + test_field_workbook 16 + test_task_interaction 13 + test_field_templates 9 + test_field_resume 7 + test_matrix_workspace 7 + test_field_row_filter 5 + test_product_matrix3 4 + test_task_button_signals 2；合并定向 76 = 定向 61 + test_task_interaction 13 + test_task_button_signals 2。
- 修复前复现（红）：接手时定向基线 1 项测试 API 误用（LogConsole.toPlainText）→ takeover-targeted-baseline.log；本会话新增边界首红 4 fail/3 error（跨原件断点复用、断点元数据歧义、超大评分 OverflowError、Excel 截断/改写未拦截）→ takeover-red.log；非法 XML 字符首红 3 fail → xml-text-red.log；旧会话留存的原始复现（100 行多表原件哈希被改、导入即建客户端、矩阵同源覆盖）→ tests-20261028-134805-615931.log、tests-20261028-134828-698048.log。修复后上述全部转绿。
- 未提交被测代码指纹：本批 8 文件最终 SHA-256 见 final-batch-sha256.json（本会话核实）与 final-sha256.json，after/ 存有同内容副本。范围核对：本批仅改 8 个授权文件，core/field_workbook.py、core/field_values.py、core/runner.py、core/main_window.py、scripts/exstract_from_description*.py 指纹与开工 baseline-sha256.json 一致（未漂移）；暂存区与开工 baseline-staged.diff 一致，本批未暂存任何改动。
- 解释器及必要环境：.venv-review/Scripts/python.exe（CPython 3.12.14）；tools/run_tests.py 有界子进程隔离加 tests/support.py 沙箱；QT_QPA_PLATFORM=offscreen；合成工作簿含多 sheet、公式与样式；类目模型全部走假 OpenAI（MagicMock）与桩 evaluator，API_KEY 为合成非可用值，未发任何真实请求；矩阵 CLI 用合成 xlsx，子进程用例走本机解释器不联网。
- 覆盖点：100 行多 sheet/公式/样式原件 SHA-256 不变（成功、失败、停止、写异常四条路径）；空输出默认旁存；显式同源与大小写/相对/规范化/硬链接别名、checkpoint 等于源或等于输出，均在读取或写入前拒绝；模型空返回、部分返回、重复 row_index、批次外行号、非法评分与枚举、超大整数、超长文本、非法 XML 字符；续跑只补失败与待审、人工确认不被覆盖、源内容或顺序或有效参数变化不误续、排序结果再作为输入按行状态续跑；写入与替换失败原目标字节不变并有界重试或保留已校验可恢复临时件；协作停止与 KeyboardInterrupt 保存已完成行、请求前停止不初始化客户端、无待处理行不初始化模型；日志与断点不泄露密钥；矩阵 CLI 子进程真实运行验证同源拒绝与另存成功，UI 断言同源不启动 runner。
- 原因：本批为源码行为变更，历史通过记录不能替代当前证据，故重跑定向与相关回归；磁盘另存的全量 405 项用于确认未波及其他模块。
- 已有失败 / 本次新增失败 / 验证局限：本批定向与相关回归无新增失败、无跳过。全量 405 项中 2 项跳过为历史已知 Windows 符号链接权限限制，非本批引入；历史审查记录的 DPAPI 环境差异本轮未触及。实屏 GUI 手动操作、收费 AI、真实采集、正式业务数据与发布 EXE 属未授权范围，其效果仍为待确认。

## 接手后的第一步

1. 交 Qoder 主会话独立只读复核：核对 4 个授权源码 diff 与 core/report_io.py，确认类目/矩阵2改动范围未越界（尤其 market_planning.py 同时含既有字段归一化改动 normalize_cb 等，本批仅动类目 tab/运行相关行，见「变更说明」）；核对 final-batch-sha256.json 与 after/、takeover/ 快照；按需重跑上述定向与相关回归命令。复核通过后再决定暂存/提交与是否进入第二批；本实施会话不自行开始第二批，也不替主会话宣布验收。

## 变更说明

以下为各文件改动要点，供复核使用；精确文件范围声明见其后的「变更文件」节。

- scripts/欧洲市场规划/类目初筛.py：R01 与 R06——输入只读、默认旁存结果、独立原子 JSON 断点加源与参数指纹（schema 2，含源路径）、处理状态与错误原因列、结果逐行严格校验、协作停止、安全原子写；导入不再强制创建客户端，无待处理行不初始化模型。
- scripts/product_matrix2.py：R02——CLI 写入前拒绝输入等于输出及别名、默认输出不落输入、export_excel 经临时件校验后原子替换、异常不破坏原目标；150/177/303 附近金额与重复键统计逻辑未改。
- modules/market_planning.py：仅类目 tab 与运行入口——默认输出与断点提示、同源与别名拒绝、停止按钮走协作停止文件、完成回调区分停止与部分失败。本文件另含此前字段归一化任务的未提交改动（normalize_cb 等），非本批所为，复核时按类目相关行区分。
- modules/product_matrix.py：仅矩阵2入口 _run_matrix2——UI 层拒绝输入等于输出及默认落输入、输出规范化为绝对 .xlsx 后传参；未改矩阵1/矩阵3。
- core/report_io.py：新增——路径规范化与同文件判定（含大小写、相对绝对、规范化与 samefile/硬链接）、默认输出与断点路径、有界退避重试、原子写 JSON 与 Excel 并完整校验（含逐单元格内容比对与公式注入防护）、SafeWriteError 保留可恢复临时件。
- tests/test_category_screening.py：新增 36 用例，假 OpenAI 加合成工作簿。
- tests/test_product_matrix2.py：新增 14 用例，含真实 CLI 子进程入口。
- tests/test_report_io.py：新增 11 用例。
- .runtime-local/review-fixes-20261028-batch1/ 与 .runtime-local/test-logs/ 为 gitignore 运行期证据，不作为提交源码列出；CURRENT.md 由主会话独占维护，非本批实施者改动，故不列入变更文件。

## 变更文件

- `scripts/欧洲市场规划/类目初筛.py`
- `scripts/product_matrix2.py`
- `modules/market_planning.py`
- `modules/product_matrix.py`
- `core/report_io.py`
- `tests/test_category_screening.py`
- `tests/test_product_matrix2.py`
- `tests/test_report_io.py`
- `handoffs/2026-10-28-review-fixes-batch1.md`

## 收工检查

- 实施与本会话自验（定向 61 + 相关 87）完成，磁盘另存合并定向 76 与全量 405 通过日志；状态置「待确认」，交主会话独立复核；未宣布最终验收完成，未进入第二批。
- 收工协作检查 `python tools/handoff.py check --repo "D:/PM Stack/PM Stack"` 返回 `Handoff check passed: 46 change(s), 7 record(s)`，退出码 0。该结果只证明记录结构与文件覆盖合规，不代表功能验收通过。
- 不修改 AGENTS.md、Git 配置或权限，不安装依赖，不暂存、不提交、不推送、不打包、不发布，不调用真实模型 API。
