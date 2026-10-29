# 品牌×分类矩阵上架年份解析修复

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-27（Asia/Shanghai）
- 负责人 / 集成人：本次矩阵年份修复 Codex 会话；asin_diagnosis 子智能体只读评审
- 用户目标及验收条件：修复“上架时间列”选“上架年份”后全部输出 1970；支持 Excel 数字年份、文本年份和完整日期，忽略空值和无效数字；重新打包默认 EXE，保留 ASIN 筛选功能。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点
- 本次负责的文件或模块：scripts/product_matrix3.py、tests/test_product_matrix3.py、CURRENT.md 与本记录；默认 dist/PM Stack.exe 本地交付。
- 公共文件协调 / 依赖任务：保留既有 16 项暂存协作检查修改、发布任务修改及已完成的 ASIN 筛选源码；研究工作树不变。子智能体只读，不并行改写源码。
- 交付方式：同主工作树本地源码及 EXE；不发布远端。

## 当前现场

- 已完成：读取规则、任务索引、模板，运行开工 status。已复现数值年份 2023/2025 经现有合并逻辑输出“上架时间:1970”，完整日期正确输出“2023/2025”。
- 已完成：增加 extract_launch_year 并接入合并变体年份汇总；四位整数/浮点整数/文本年份（含 .0、年 后缀）直接提取，完整日期/文本日期保留。无效数字与空值不生成错误年份，真实 1970 年日期正常显示。
- 已完成：新增 4 项回归，旧代码上有效复现失败；修复后与矩阵、任务交互和 ASIN 看板相关共 53 项通过。只读评审通过，无阻断问题。
- 已完成：候选 EXE 构建及隔离启动/看板自检通过，ASIN 筛选仍正常。已确认 EXE 内嵌的矩阵脚本及 ASIN 模块与工作树逐字节相同；用匹配构建解释器执行提取的矩阵脚本，真实生成 XLSX 并核对三张商品卡片的年份、最高销量代表和空年份。
- 已完成：已替换默认 dist/PM Stack.exe，大小 133781664，SHA-256 为 759c548e7914ae7cbf2c902c77ff22cdb0b5c755b41cd9d222dcbc4f51884c4c；交付哈希与已验证候选一致。
- 未完成 / 已知问题：本次修复与本地 EXE 交付无剩余步骤；旧导出文件需用户重新生成，未改写用户现有矩阵文件。未格式化的裸 Excel 日期序号无日期系统信息，仍不猜测转换。
- 未提交修改与未跟踪文件：本任务 scripts/product_matrix3.py、tests/test_product_matrix3.py、本记录与索引尚未暂存；开工已有 ASIN 筛选、发布和协作修改均保持。
- 已提交但未共享的内容：本任务无提交。
- 恢复位置：当前主工作树；交付前含 ASIN 筛选的 EXE 备份在 .runtime-local/matrix-year-20261027/before-delivery/PM Stack.exe（SHA-256 2341b547e50034b6c0ce6e2c3071f53799a7b947f924bac74679e799570f75bd）。候选、输出验证表及自检报告在同任务目录。

## 决策及原因

- 2026-10-27：仅修复合并变体的年份汇总，不改独立排序入口或用户配置。四位整数年份直接取年，完整日期继续取年；不把裸数字当作 Unix 纳秒，也不猜测缺少日期格式/日期系统信息的 Excel 序号。
- 2026-10-27：保留真实 1970 年日期，不靠屏蔽 1970 掩盖解析错误。空值、布尔、非整数年份及其他无效数字不生成年份行。
- 2026-10-27：沿用 v1.11.5 spec 和内部版本进行本地修复交付；不更新公开清单、release/current 或历史归档。复用同主工作树的构建缓存，候选及日志独立保存于本任务目录。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-27 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 未提交被测代码：最终 SHA-256：scripts/product_matrix3.py = 0402edb35fc852fd775288db00fc9c1bab628b7da85f952afe45c5d52748b840；tests/test_product_matrix3.py = a2cd7616f0ebe3c2dc3d9dc8f675761c974cf1a9c798490129231d6bc86e6df7。既有 ASIN 模块 modules/display_dashboard.py 指纹保持 e636f0beedea54b6a2b06590dbafcbfcc941b4cf016cf2b590f259c04748ae93。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_task_interaction tests.test_matrix_workspace --timeout 240
- 解释器及必要环境：.venv-review，Python 3.12.14；测试使用 tools/run_tests.py 隔离用户路径、Qt offscreen。
- 结果：20 项基线通过；日志 .runtime-local/test-logs/tests-20261027-145211-765851.log。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_product_matrix3 --timeout 120
- 结果：在旧代码上运行新增 4 项回归，得到 8 个失败（含无效输入子测试），直接复现 Excel 上架年份输出 1970；这是修复前的预期失败。日志 .runtime-local/test-logs/tests-20261027-145505-415589.log。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_product_matrix3 tests.test_task_interaction tests.test_matrix_workspace tests.test_dashboard --timeout 240
- 结果：最终 53 项全部通过，日志 .runtime-local/test-logs/tests-20261027-145536-317074.log。实际经 Excel 数值年份读入→变体合并→输出 XLSX 验证，上架时间为 2023/2024/2025，最高销量代表子体及原始工作簿字节保持正确；完整日期、文本年份、去重排序、缺失和无效数字、真实 1970 日期均覆盖。
- 命令：.venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/matrix-year-20261027/candidate --workpath build/asin-filter-20261027 "PM Stack v1.11.5.spec"
- 解释器及必要环境：Python 3.12.14，既有 .venv-review；依照项目构建规则过滤 PATH 中无关 Poppler/libheif/jxrlib，不安装/升级依赖。EXE 自检隔离 LOCALAPPDATA/USERPROFILE/TEMP/TMP，Qt offscreen，关闭自动更新。
- 结果：构建成功；日志 .runtime-local/matrix-year-20261027/build.log。
- 命令：.venv-review/Scripts/python.exe .runtime-local/matrix-year-20261027/verify_package.py
- 结果：候选内嵌 scripts/product_matrix3.py、modules/display_dashboard.py、core/dashboard_smoke.py 与源码逐字节相同。提取的真实内嵌脚本用构建解释器执行 CLI，输出 .runtime-local/matrix-year-20261027/embedded-script-check/matrix.xlsx，三个商品格分别为“上架时间:2023/2025”、“上架时间:2024”、不显示空年份，输入表字节保持不变；日志在同目录 cli.log。此步骤运行的是 EXE 内嵌脚本，不声称为 GUI 点击生成。
- 结果：候选真实 EXE --startup-check 与 --dashboard-check 成功，ASIN 自检 ok；报告 .runtime-local/matrix-year-20261027/package-smoke/startup.json、dashboard.json，完整指纹及输出格内容在 .runtime-local/matrix-year-20261027/package-evidence.json。替换 dist 后重新计算 SHA-256 与验证候选一致。
- 原因：本次采用合成数据和隔离临时表验证，不读取用户实际工作簿，也不覆盖 dist/product_matrix3.xlsx。
- 已有失败 / 本次新增失败 / 验证局限：修复后的相关回归无失败；用户实际工作簿未做人工验收。

## 接手后的第一步

1. 无开发或打包待办；打开 dist/PM Stack.exe，继续选择“上架年份”或真实“上架时间”，重新生成矩阵。用户截图中的“销量列”应手动选择实际销量字段，未替用户改动配置。验收依据为 53 项相关回归、内嵌脚本导出验证及 EXE 自检。

## 变更文件

- `scripts/product_matrix3.py`
- `tests/test_product_matrix3.py`
- `CURRENT.md`
- `handoffs/2026-10-27-matrix-launch-year.md`

## 收工检查

- 开工 status、交付前后哈希已核验；收工工作区 check 与 diff --check 见本次执行输出。保留既有 16 项暂存修改，本任务未暂存、提交或推送。
