# 2026-10-27：字段格式与度量单位归一化设计与实现

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-27（Asia/Shanghai）
- 负责人 / 集成人：本次字段归一化方案的 Codex 会话
- 用户目标及验收条件：用户已授权实现提取后自动批量归一化：每特征统计不同结果与频次，AI建立映射，程序校验后修正全部对应ASIN行；特征可受控并行，不要求额外历史入口或手动维护两套结果。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 7245d83cdc672636dcf344ee33319cf29a518957
- 本次负责的文件或模块：共享字段归一化、两份提取脚本、限定范围的写回、界面开关及相关隔离测试；保留其他任务修改。
- 公共文件协调 / 依赖任务：顺序继任索引协调；保留既有矩阵、看板、发布及协作检查任务全部修改。
- 交付方式：同工作树源码与本地dist/PM Stack.exe交付；未提交、推送或发布远端。

## 当前现场

- 已完成：共享归一化模块、默认开启的UI开关、两份提取脚本接入、显式原值检查的限定写回、字段并发/大词表分批、原值与冻结映射旁车、停止恢复、单位与映射完整性校验；新增24项隔离测试。最终全量344项中342项通过、2项系统权限跳过。
- 已完成：候选EXE构建、9份内嵌源码逐字节核对与PYZ模块检查通过。提取出的两份真实打包脚本均完成600行/50种原值→10个标准值，替代模型各调用1次，第二轮复用映射调用0次。真实EXE启动与看板ASIN筛选自检通过，已备份并替换默认dist/PM Stack.exe。
- 未完成 / 已知问题：本轮代码与本地打包交付无剩余步骤。真实模型语义准确率需代表数据确认；本次使用合成数据及替代模型，未消耗真实API或改写用户工作簿。历史已丢失的含义不能推断恢复。
- 未提交修改与未跟踪文件：本任务文件见下方精确清单，新核心与测试尚未跟踪。开工已有协作机制、发布、看板、矩阵等暂存与未暂存修改均保留；本轮不改暂存区，打包包含主工作树此前已完成的本地修复。
- 已提交但未共享的内容：本任务无提交。
- 恢复位置：当前工作树、本任务记录及.runtime-local/field-normalization-20261027。交付前EXE备份位于该目录before-delivery/PM Stack.exe（SHA-256 759c548e7914ae7cbf2c902c77ff22cdb0b5c755b41cd9d222dcbc4f51884c4c）。docs/仍被现有规则忽略，新方案为本地忽略文件；未来提交/异机交接须显式纳入，不能仅提交导航链接。本轮仅新增私有运行旁车的*.normalization.json忽略规则。

## 决策及原因

- 2026-10-27：用户明确“可以，去做吧”，开始实施上述澄清后的设计。UI默认启用；旧脚本直接调用需显式启用以兼容既有任务与测试。写回只接受带原值检查的特定单元格替换计划。
- 2026-10-27 用户澄清后的当前决策：每特征全部不同结果交给AI建立映射，程序校验后自动应用；优先集成提取后流程。不同特征受控并行、Excel单写入者。首期取消历史独立入口、逐字段类型配置与逐批人工接受；此前下列相关安排仅作修订历史，不再执行。
- 2026-10-27：原值记录作为后台任务恢复与变更追踪，不要求用户维护原值列或额外表格；业务列直接显示修正值。
- 2026-10-27：单值度量在模型映射后统一为数值紧接标准单位，校验换算数值；型号、范围、矛盾单位及不明语义保留。超过80项或字符预算时分批并冻结同一表达约定；不保证未覆盖表达强制归并。
- 2026-10-27：沿用v1.11.5 spec及内部版本交付本地更新，不改公开清单、release归档或远端latest。新增hidden import保证运行内嵌脚本时共享模块可用。

以下为此前设计阶段的修订历史，已被上述用户澄清和实施决定替代：

- 2026-10-27：沿用通用字段配置、固定规则与可复用映射，不逐类目开发专用脚本；用户主要目标是格式和单位统一。
- 2026-10-27：优先独立整理已有表格，再接入后续提取，避免被现有只补空保护阻断历史治理。
- 2026-10-27：AI按不同原值批量建议，新映射经预览接受；已接受版本确定应用，不能将固定结果视为正确性证明。
- 2026-10-27：默认另存副本、保留原值及规则版本；数值与单位分开保存，不用舍入合并真实差异。
- 2026-10-27：用户请求为设计，本轮只交付文档，不执行方案中的代码改动。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-27 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 未提交被测代码：精确指纹在.runtime-local/field-normalization-20261027/source-fingerprints.json；核心core/field_normalization.py SHA-256为85d3efd27cb937d8b2601cf9d744ca73bc3fcf7801be385a636b40912d25e2ae，测试tests/test_field_normalization.py为e1da5ccc886016bed036a862501858c86fe0a4a172cd1bc8ae915b193fe3c690。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_field_workbook tests.test_field_resume tests.test_field_templates tests.test_field_row_filter --timeout 240
- 解释器及必要环境：既有.venv-review，Python 3.12.14；tools/run_tests.py隔离用户目录、Qt offscreen，不安装或升级依赖。
- 结果：修改前37项基线通过，日志.runtime-local/test-logs/tests-20261027-232914-284586.log。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_field_normalization --timeout 240
- 结果：新增24项全部通过，日志.runtime-local/test-logs/tests-20261027-234610-266540.log。覆盖600/50批量链路、完整性校验、单位核验、并行、停止/恢复、失效、独立输出、原值竞争、公式与图片等。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py --timeout 300
- 结果：最终344项中342项通过、2项因Windows符号链接权限跳过，日志.runtime-local/test-logs/tests-20261027-234820-248735.log。正常Windows上下文执行，DPAPI凭据用例通过；沙箱先前全量的2项凭据失败已确认是环境限制，单独正常上下文重测亦通过，日志.runtime-local/test-logs/tests-20261027-234701-270510.log。
- 命令：.venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/field-normalization-20261027/candidate --workpath build/asin-filter-20261027 "PM Stack v1.11.5.spec"
- 结果：候选构建成功，日志.runtime-local/field-normalization-20261027/build.log；过滤PATH内无关Poppler/libheif/jxrlib，复用现有解释器与构建缓存。
- 命令：.venv-review/Scripts/python.exe .runtime-local/field-normalization-20261027/verify_package.py
- 结果：9份真实内嵌源码逐字节匹配，PYZ含新模块；提取的串行/并发脚本在匹配解释器上各处理600行并验证恢复；真实EXE --startup-check和--dashboard-check通过。完整证据在.runtime-local/field-normalization-20261027/package-evidence.json，运行日志在同目录verify.log及各脚本log。该脚本链路不是声称GUI实际点击或真实付费模型调用。
- 结果：默认dist/PM Stack.exe已替换，大小133817464字节，SHA-256为1478b2ce2e1e03fc4c83b95502d3a6721a74fa0aa6df7d3c85d48ae2a296bd95，与验证候选一致；交付和备份指纹在.runtime-local/field-normalization-20261027/delivery-evidence.json。
- 命令：D:\PM Stack\协作检查.cmd status；D:\PM Stack\协作检查.cmd check；git diff --check。
- 结果：开工状态和交接检查通过；收工再次检查结果以本轮工具输出为准，所有其他任务修改与暂存区保留。
- 原因：使用合成数据与替代模型，避免测试消耗真实API或改写用户工作簿。
- 已有失败 / 本次新增失败 / 验证局限：最终回归没有失败，2项权限跳过；真实语义映射准确性尚未实测。初期数字格式保留用例发现写表器重设原有目标列样式，已修复并回归；未修改凭据模块。

## 接手后的第一步

1. 本轮无代码或打包待办。打开dist/PM Stack.exe，在市场规划→字段提取保持默认勾选“提取后自动归一化”，执行所选字段；可按需用代表真实表验收模型语义效果。若继续迭代沿用本记录，不恢复已被替代的历史入口/强制审核方案。

## 变更文件

- `.gitignore`
- `PM Stack v1.11.5.spec`
- `core/field_normalization.py`
- `core/field_values.py`
- `core/field_workbook.py`
- `scripts/exstract_from_description.py`
- `scripts/exstract_from_description_fast.py`
- `modules/market_planning.py`
- `tests/test_field_normalization.py`
- `docs/字段格式与单位归一化方案-2026-10-27.md`
- `docs/产品信息提取改进方案-2026-10-23.md`
- `handoffs/2026-10-27-field-normalization-design.md`
- `CURRENT.md`

## 收工检查

- 本次源码、测试、文档与默认EXE本地交付完成；没有暂存、提交、推送或发布远端，没有改写用户工作簿。
- 主索引已登记本地实施完成，保留其他任务状态。
- 收工检查与本地链接验证以本轮命令实际输出为准，不能代替功能验收。
