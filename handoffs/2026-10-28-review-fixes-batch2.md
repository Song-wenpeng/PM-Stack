# 2026-10-28：审查修复第二批——矩阵统计口径与机会评分日期

## 接手信息

- 状态：待确认
- 更新日期与时区：2026-10-28（Asia/Shanghai）
- 负责人 / 集成人：本次 Qoder 主会话直接实施并自证；用户在第一批复核通过后免实屏验证授权继续，验收决定仍归用户。
- 用户目标及验收条件：按合并审查路线修 A 报告 R03 与 R04。矩阵金额不再因格式被静默丢弃，缺失金额不等于零并明确区分，重复 ASIN 关联不再放大金额与数量；机会评分不再使用写死的过期分析日期，分析基准日显式可设并写入参数快照，相对分位打分口径在输出中说明。既有正确数据的矩阵单元格格式与数值保持不变。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点，本批不提交故 HEAD 未变
- 本次负责的文件或模块：销额矩阵2统计与输出、机会得分脚本及其 UI 入口、共享基准日解析工具、对应定向测试；精确路径见「变更文件」。
- 公共文件协调 / 依赖任务：第一批已交付待确认，本批在其成果之上继续。沿用 core/report_io.py 安全落盘并新增一个基准日解析函数，未修改该模块既有函数语义；第一批的类目脚本、矩阵 UI 入口与类目测试经指纹比对确认逐字节未变。modules/market_planning.py 同时含第一批类目改动与此前字段归一化改动，本批只动机会得分 tab 与 _run_scoring。CURRENT.md 由主会话独占维护。不操作研究工作树，不修改 runner/main_window 等后续批次范围。
- 交付方式：同工作树串行实施，不暂存、不提交、不推送、不打包、不发布。

## 当前现场

- 已完成：
  - R03 金额解析：新增 parse_amount 与 parse_amount_column，兼容千分位逗号、货币符号（欧元、美元、英镑、日元、人民币、卢比）、欧式「1.234,56」、会计负数括号与前后空白；不可解析的值不再静默变 NaN，而是计数、给出样例并写入「参数信息」表。
  - R03 缺失与零分离：单元格计数与均值只按有有效金额的行计算，缺失行数单独标出；全部缺失时输出「无有效金额（N行）」而不是「0 (N个, 0.0均)」；合计行同样区分。有效数据的单元格格式与数值保持原样。
  - R03 重复关联：子表 ASIN 重复时先去重再左连接，并告警与登记重复个数；合并后行数若变化额外告警。元数据重复 ASIN 只告警并登记多出行数，不自动删除，避免替用户判断源数据。
  - R04 分析基准日：移除写死的 2026-04-15，改为默认运行当日、可由界面「分析基准日」或 MARKET_ANALYSIS_DATE 显式指定；只接受明确的年月日写法，模糊或非法值直接报错而不猜测。
  - R04 异常暴露：上架时间晚于基准日时按类目告警并计入「上架晚于基准日数」，上架时间缺失计入「上架时间缺失数」，负天数不再静默进入新品判定与爬坡效率。
  - R04 可追溯：输出新增「参数快照」表，记录基准日及其来源、新品天数阈值、参与文件数与文件名、成功汇总类目数、原始行数、总分构成、打分方式与生成时间；「评分说明」新增两行明确各维度是本次参与类目之间的相对分位、参与文件变化会影响分数与标签。
  - 附带修复：机会得分脚本原为模块级立即执行代码，导入即扫描真实目录，无法在不触盘的前提下测试；重构为函数加 `__main__` 守卫，评分公式、权重、列名候选与 Top100 截取逐字保留。load_excel_file 改用上下文管理器关闭句柄，此前未关闭会在 Windows 上一直占用用户源文件。
  - 输出安全：机会得分改走 core.report_io.write_excel 原子落盘，输入目录中的全部类目文件列为保护路径，且输出文件本身会从候选输入中排除，避免上一次结果被当作类目数据读入。
  - 定向回归 107 项通过，全量隔离回归 436 项通过、2 项因 Windows 符号链接权限跳过；协作检查通过。
- 未完成 / 已知问题：实屏 GUI 手动操作、真实市场数据与真实 EXE 未验证；R05 关窗不等 daemon 保存、R07 坏配置阻止启动、R08 小屏几何、R09 备份凭据、R10 视觉模型文案、R11 自由矩阵 GUI 线程读取均不在本批范围。类目停止信号文件在状态目录累积的小问题仍留待后续批次。
- 未提交修改与未跟踪文件：第一批与本批成果均未暂存未提交；暂存区经字节比对与第一批开工基线一致（staged_area_identical_to_batch1_baseline=true）。
- 已提交但未共享的内容：本批无提交。
- 恢复位置：.runtime-local/review-fixes-20261028-batch1/ 为第一批只读依据；.runtime-local/review-fixes-20261028-batch2/final-sha256.json 为本批 7 个文件指纹、暂存区比对、第一批未触及文件的逐字节确认及红绿日志索引。均为只读依据，不授权恢复或重置现场。

## 决策及原因

- 2026-10-28：第一批实施子会话两次无故中断，用户在第一批复核通过后要求直接继续，故本批由主会话直接实施，避免再次因中断丢失收尾；不因此扩大提交或发布授权。
- 2026-10-28：金额解析改为显式清洗并在失败时计数加样例，原因是 `pd.to_numeric(errors='coerce')` 会把「1,200」变 NaN 后从合计中消失，用户看到的是偏小的数字而不是错误；审查证据中该行合计为 300 而非 1500。
- 2026-10-28：不把「N/A」「NA」等 pandas 读表阶段即转为 NaN 的文本当作不可解析，而计入空值。这类值确实表示缺失；真正无法解析的文本（如「待定」「约1千」）才计数并给样例，避免把两类问题混为一谈。
- 2026-10-28：区分「无数据」与「销额为零」。全部缺失时输出明确的缺失标记而不是 0，因为 0 会被读成该细分市场卖得为零。
- 2026-10-28：子表按 ASIN 去重后再关联，重复项计数并告警；元数据重复 ASIN 只告警与登记不自动删除，因为是否重复录入需由用户按源数据判断，自动删除会改变既有口径。
- 2026-10-28：分析基准日默认取运行当日，而不是沿用写死日期或从数据推断。「上架天数」「是否新品」必须相对一个明确时点计算，写死过期日期会让该日之后上架的商品得到负天数并被漏判为非新品（审查证据：2026-07-01 上架得到 -77 天）。
- 2026-10-28：基准日只接受明确的年月日写法（连字符、斜杠、点号分隔，允许不补零），不接受会被 pandas 随意推断的模糊字符串；日在前的欧式写法直接报错，避免 01/02 这类歧义被静默解释。
- 2026-10-28：基准日解析放入 core/report_io.py 供脚本与界面共用，避免两处格式口径不一致；这是新增函数，不改动该模块既有函数语义。
- 2026-10-28：机会得分输出增加参数快照表并在评分说明中写明相对分位口径，使分数可追溯；审查报告 B 指出相对分数缺少说明，容易被当成绝对结论。
- 2026-10-28：输出文件从候选输入中排除而不是直接报错，因为把输出写在数据目录里是常见做法，硬失败会挡住正常使用；排除并告警既不丢数据也不污染统计。同时把所有输入文件列为写保护路径，输出永不覆盖它们。
- 2026-10-28：机会得分脚本重构为函数加 `__main__` 守卫是测试可行性的前提，不是为重构而重构；评分公式与权重逐字保留，并由结构回归用例守住总分等于五维之和、落在 0 到 100、标签属于 A/B/C/D。
- 2026-10-28：load_excel_file 改用上下文管理器，因为未关闭的 ExcelFile 句柄在 Windows 上会持续占用用户源文件，本批测试的临时目录清理即因此失败，真实场景下用户会遇到文件无法移动或覆盖。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-28 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 未提交被测代码指纹：本批 7 个文件 SHA-256 见 .runtime-local/review-fixes-20261028-batch2/final-sha256.json；其中 batch1_files_verified_unchanged 以第一批指纹逐项比对，确认 scripts/欧洲市场规划/类目初筛.py、modules/product_matrix.py、tests/test_category_screening.py 三个第一批文件本批未被改动；staged_area_identical_to_batch1_baseline=true 确认暂存区与第一批开工基线字节一致，本批未暂存任何改动。
- 命令：修复前红 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_market_scoring tests.test_product_matrix2.Matrix2StatisticsTests --timeout 240`；矩阵阶段 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_product_matrix2 --timeout 240`；机会得分阶段 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_market_scoring --timeout 240`；定向 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_market_scoring tests.test_product_matrix2 tests.test_report_io tests.test_category_screening tests.test_task_interaction tests.test_task_button_signals --timeout 300`；全量 `.venv-review/Scripts/python.exe tools/run_tests.py --timeout 600`；协作检查 `python tools/handoff.py status --repo "D:/PM Stack/PM Stack"` 与 `python tools/handoff.py check --repo "D:/PM Stack/PM Stack"`。
- 结果：修复前红 Ran 19 tests，FAILED failures=13 errors=8（tests-20261028-143343-680144.log），其中机会得分基准日用例复现出与审查证据完全一致的 -77 天，默认基准日用例复现 -166 天；矩阵阶段 Ran 25 tests OK（tests-20261028-144105-427777.log）；机会得分阶段 Ran 13 tests OK（tests-20261028-145108-800060.log）；定向 Ran 107 tests OK 退出码 0（tests-20261028-145837-660630.log）；全量 Ran 436 tests OK skipped=2 退出码 0（tests-20261028-145909-008954.log），较第一批全量 405 项净增 31 项。
- 覆盖点：金额解析单元用例覆盖整数、浮点、千分位、欧元与美元符号、欧式与英美式分隔符冲突、会计负数括号、前后空白、零、None、NaN、空串、纯符号、「待定」「约1千」「12ab」「12%」等不可解析文本、布尔与无穷；矩阵端覆盖多格式金额合计正确、全缺失标记为非零假象、部分缺失只对有效行求均值、不可解析计数与样例进日志与参数表、pandas 读表即转 NaN 的文本计入空值而非不可解析、子表重复 ASIN 不放大金额与个数、元数据重复 ASIN 告警且不静默删除、有效数据单元格格式与数值不变。机会得分端覆盖导入不扫描目录不写文件、显式基准日驱动上架天数、默认基准日为运行当日、非法与歧义基准日在写入前失败且给出环境变量名、四种合法写法被接受、留空回落运行当日、上架晚于基准日告警且不计新品、参数快照记录基准日与来源与阈值与文件清单、评分说明含相对分位口径、输出落在数据目录时第二次运行不把上次结果当输入、源文件字节不变、数据目录缺失时明确失败、总分等于五维之和且落在 0 到 100 且标签合法。UI 端覆盖提示显示运行当日默认与相对分位说明、显式基准日透传给脚本、留空透传为空由脚本回落、非法基准日不启动 runner 并在提示与日志内联报错。
- 解释器及必要环境：.venv-review/Scripts/python.exe（CPython 3.12.14）；tools/run_tests.py 有界子进程隔离加 tests/support.py 沙箱；QT_QPA_PLATFORM=offscreen；合成类目工作簿与合成矩阵工作簿；本批不涉及任何模型请求，无网络调用，无真实业务数据。
- 原因：本批直接改变业务统计输出与评分口径，历史通过记录不能替代当前证据，故先写失败复现再修复，并跑定向与全量回归；同时以指纹比对证明第一批成果未被本批意外改动。
- 已有失败 / 本次新增失败 / 验证局限：本批无新增失败。全量 2 项跳过为历史已知的 Windows 符号链接权限限制，非本批引入。过程中出现过两次测试自身前提错误并已修正：一是把「N/A」当作不可解析文本，实际 pandas 读表阶段即转为 NaN 属真实缺失；二是把斜杠日期当作非法值，实际斜杠是本批有意支持的合法写法。两处均为测试断言错误，不是应用缺陷，修正后未降低任何断言强度。实屏 GUI 手动操作、真实市场数据与发布 EXE 属未授权范围，故其效果仍为待确认。

## 接手后的第一步

1. 等待用户对第一批与第二批的验收决定。获授权后按第三批范围处理 R05（关窗与更新退出不等待 daemon 脚本保存）、R07（坏配置 JSON 阻止启动）及模块导入与 Widget 构造容错，不夹带本批文件以外的改动。

## 变更说明

以下为各文件改动要点，供复核使用；精确文件范围声明见其后的「变更文件」节。

- scripts/product_matrix2.py：R03——新增 parse_amount、parse_amount_column、report_amount_quality 与 format_cell；build_matrix 改为返回金额质量统计并只对有效金额行计数求均值；export_excel 增加缺失标记与诊断信息写入「参数信息」；main 增加子表 ASIN 去重告警、元数据重复 ASIN 告警、合并行数变化告警与诊断汇总；矩阵预览对无有效金额单元格显示缺金额而不是 nan。统计维度定义与权重未改。
- scripts/欧洲市场规划/机会得分.py：R04——移除写死基准日，新增 resolve_analysis_date、collect_files、apply_scores、classify_tag、make_recommendation、build_score_guide、build_snapshot、main 与 `__main__` 守卫；summarize_category_file 改为按传入基准日计算并告警晚于基准日与缺失上架时间；输出改走 write_excel 原子落盘并保护全部输入文件；评分说明补充相对分位与基准日两行。评分公式、权重、列名候选、Top100 截取与排序逻辑逐字保留。
- core/report_io.py：新增 REFERENCE_DATE_FORMATS 与 resolve_reference_date，供脚本与界面共用基准日解析；既有函数未改语义。
- modules/market_planning.py：仅机会得分 tab 与 _run_scoring——新增「分析基准日」输入与实时提示，启动前校验基准日格式并内联报错，把 MARKET_ANALYSIS_DATE 透传给脚本。本文件另含第一批类目改动与此前字段归一化改动，非本批所为。
- tests/test_market_scoring.py：新增 17 用例，覆盖脚本行为与机会得分 tab 的 UI 保护，全部使用合成类目工作簿。
- tests/test_product_matrix2.py：新增 AmountParsingTests 2 用例与 Matrix2StatisticsTests 9 用例，共 11 用例，并更新模块 docstring。
- tests/test_report_io.py：新增 ReferenceDateTests 3 用例，并更新模块 docstring。
- .runtime-local/review-fixes-20261028-batch2/ 与 .runtime-local/test-logs/ 为 gitignore 运行期证据，不作为提交源码列出。

## 变更文件

- `CURRENT.md`
- `handoffs/2026-10-28-review-fixes-batch2.md`
- `core/report_io.py`
- `modules/market_planning.py`
- `scripts/product_matrix2.py`
- `scripts/欧洲市场规划/机会得分.py`
- `tests/test_market_scoring.py`
- `tests/test_product_matrix2.py`
- `tests/test_report_io.py`

## 收工检查

- 实施、定向与全量回归、指纹与暂存区比对均已完成，状态置「待确认」，等待用户验收；未宣布最终验收完成，未进入第三批。
- 收工协作检查 `python tools/handoff.py check --repo "D:/PM Stack/PM Stack"` 返回 Handoff check passed: 49 change(s), 8 record(s)，退出码 0；开工时另执行 `python tools/handoff.py status --repo "D:/PM Stack/PM Stack"` 确认目录、分支、HEAD 与钩子位置。该结果只证明记录结构与文件覆盖合规，不代表功能验收通过。
- 全量回归之后仅修改了本记录、CURRENT.md 与 .runtime-local 证据 JSON，未再触碰任何源码或测试；文件指纹以 final-sha256.json 为准。
- 不修改 AGENTS.md、Git 配置或权限，不安装依赖，不暂存、不提交、不推送、不打包、不发布，不调用真实模型 API。
