# 2026-10-29：仅恢复自由组合矩阵v1.10.7旧布局

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-29（Asia/Shanghai）
- 负责人 / 集成人：本次Codex会话，继续负责主索引
- 用户目标及验收条件：用户已明确选择恢复10月8日v1.10.7旧布局；只恢复自由组合矩阵，保留其他更新；回归验证后重新打包并替换dist/PM Stack.exe。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点
- 本次负责的文件或模块：core/matrix_workspace.py及直接依赖新版布局的测试断言；具体路径见变更文件。
- 公共文件协调 / 依赖任务：同工作树串行执行，只读审查员不修改代码；保留原暂存区与既有修复，不操作研究工作树。
- 交付方式：同工作树单模块回退，本地EXE和干净分发ZIP，不提交、不推送、不发布。

## 当前现场

- 已完成：按用户选择从v1.10.7原始EXE恢复单个主体源码，宿主补1行兼容标记；同步3份布局相关测试，定向52项通过，全量505项中503通过、2项权限跳过；独立复核4项通过；候选EXE内嵌源码/编译模块一致性及3类实际自检通过；旧布局合成数据预览和真实Excel导出验证通过；用户关闭运行中应用后已替换dist/PM Stack.exe并生成2026-10-29分发ZIP、说明及摘要。
- 未完成 / 已知问题：本次选定旧布局恢复无剩余步骤；旧版渲染与当前核心分组逻辑相近，恢复布局不等于证明用户截图空白问题已经修复。真实业务工作簿与实屏效果仍待实际使用验收。
- 未提交修改与未跟踪文件：开工65项既有变更保留；新增单模块回退与相关测试和记录，最终70项变化，12份有效交接记录。原有暂存区保持，未提交/推送。
- 已提交但未共享的内容：无本次提交。
- 恢复位置：.runtime-local/free-matrix-rollback-20261029/保存回退前源码、指纹、索引快照、EXE备份和验证报告。

## 决策及原因

- 2026-10-29：用户在明确两个回退点差异后选择v1.10.7旧布局。仅从现存该版EXE提取单个源码，其他文件不从历史版本恢复；保留10月28日四批修复、补修和看板联动。
- 2026-10-29：旧版采用上方横向分组、左侧纵向分组和中间矩阵，不包含右侧可收起配置栏，也不包含后续按钮禁用控制。测试改为验证选定的旧布局、可调整区域及无数据时执行导出的保护，不保留已撤回界面的实现断言。
- 2026-10-29：原始旧源码SHA256为7e77a619d11eb4201ab71236dade89977e795a1c419c3bef59d23187cf8c45fb；回退后将验证逐字节相同，不混入新功能或重构。
- 2026-10-29：首次定向52项中2项失败，定位为旧版没有workspacePage标记，当前ScrollTabs将其额外包裹，导致直接切换自由矩阵及看板跳转失效；在modules/product_matrix.py实例化处补1行宿主适配标记，保持旧版主体逐字节一致，保留当前看板跳转行为。不修改共享ScrollTabs或其他子矩阵。
- 2026-10-29：构建和干净分发ZIP先完成，检测到用户仍在运行dist主程序（PID3880/8784，启动器及子进程），因此请用户保存关闭；收到明确“已关闭PM Stack”后复查无目标进程，再执行替换，不强杀用户应用。原主程序备份于.runtime-local/free-matrix-rollback-20261029/previous/PM Stack.exe。

## 验证证据

- 执行日期 / 工作目录 / 分支与HEAD：2026-10-29 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 未提交被测代码：.runtime-local/free-matrix-rollback-20261029/baseline-sha256.json与final-source-sha256.json共158文件；仅core/matrix_workspace.py、modules/product_matrix.py和3份列明测试变化，其余153文件逐字节不变。baseline-index.patch与final-index.patch逐字节相同。主体与v1.10.7 CArchive中资源字节一致，SHA见决策。
- 命令：`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_matrix_workspace.MatrixWorkspaceTests.test_legacy_split_layout_resizes_without_changing_matrix --timeout 120`；`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_matrix_workspace tests.test_task_interaction tests.test_clean_layout tests.test_dashboard --timeout 240`；`.venv-review/Scripts/python.exe tools/run_tests.py --timeout 600`。
- 解释器及必要环境：.venv-review CPython3.12.14、PyInstaller6.22.2，tests/support.py隔离沙箱及offscreen Qt；全量在正常Windows用户上下文运行以支持DPAPI测试；不访问真实模型或业务文件。
- 结果：旧布局验收在回退前失败（workspace_split为3区而非2区），日志tests-20261029-000626-266441.log；回退后首轮52项有2项导航失败，日志tests-20261029-000642-432503.log；宿主适配后52项全部通过，日志tests-20261029-000840-810260.log。最后保留按钮在窗内的强断言，完整505项实际503通过、2项Windows符号链接权限跳过，无失败/错误，日志.runtime-local/test-logs/tests-20261029-000947-557602.log；独立审查关键4项实际执行全部通过。
- 构建命令：过滤本构建进程PATH的不相关Poppler/图像工具DLL路径后，`.venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/free-matrix-rollback-20261029/candidate --workpath build/free-matrix-rollback-20261029 "PM Stack v1.11.5.spec"`，退出0，日志build.log。
- 包自检命令：PYTHONIOENCODING=utf-8后，`.venv-review/Scripts/python.exe .runtime-local/free-matrix-rollback-20261029/verify_candidate.py`，退出0。87份内嵌资源源码、55个core/modules编译模块和main与当前源码一致；启动/矩阵预览、展示看板576行数据ASIN筛选与矩阵跳转、销量拆分按钮与名单提取三类实际EXE自检全部退出0，报告package-verification.json、startup.json、dashboard.json、sales-split.json。
- 布局与导出：`.venv-review/Scripts/python.exe .runtime-local/free-matrix-rollback-20261029/preview_legacy.py`，4个合成商品生成2x2旧布局，原工作簿字节不变，导出产品明细4个ASIN完整；报告legacy-preview.json与restored-layout.png。源码进程首次隔离截图因字体枚举显示方框，预览工具显式加载本机微软雅黑后已重绘并目视检查清晰，未为此修改应用源码。
- 交付命令：`.venv-review/Scripts/python.exe .runtime-local/free-matrix-rollback-20261029/package.py`先生成ZIP，用户关闭主程序后`.venv-review/Scripts/python.exe .runtime-local/free-matrix-rollback-20261029/install.py`完成替换，均退出0。EXE133860329字节，SHA256为8e6b097bad89db9086cc0ecf1dcce35e16cdff17ec53529e41072b3620dc8aa0；ZIP140814727字节，SHA256为f00a9025101d826b0268791a4addd611485e18aa141f54b19d71c3f7547c70d8。ZIP11条目CRC与逐项SHA一致，仅含程序、更新器、通道、扩展6文件、说明和摘要；不含用户数据。替换前主程序SHA为142a22cf6d4f75b7576dc0ee9ca8408b7dc49bafdebc6f55f1bb1368d7a09758，已备份。
- 原因：按用户选定的历史版本恢复，需要验证与当前其他模块接口兼容。
- 已有失败 / 本次新增失败 / 验证局限：旧版无右侧折叠配置与预览前禁用按钮，相关测试已随用户明确授权回退更新；导航兼容性新增失败已定位并修复，最终无失败；真实业务表格空白现象未复现，不能宣称已解决。

## 接手后的第一步

1. 本轮回退与本地打包已完成，可重新启动dist/PM Stack.exe确认旧布局；若继续处理原截图空白，先以用户指定工作簿只读复现分组与可见区域，再确定根因，不把此次回退当作根因修复证据。

## 变更文件

- `CURRENT.md`
- `handoffs/2026-10-29-free-matrix-rollback.md`
- `core/matrix_workspace.py`
- `modules/product_matrix.py`
- `tests/test_matrix_workspace.py`
- `tests/test_clean_layout.py`
- `tests/test_task_interaction.py`

## 收工检查

- 开工status、收工handoff check通过（70项变更、12份记录）；原暂存区逐字节不变。源码回退范围与其他153文件未漂移已由独立审查复核，用户确认关闭后完成正式EXE替换；未提交、未推送、未发布。
