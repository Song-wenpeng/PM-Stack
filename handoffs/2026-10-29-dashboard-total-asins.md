# 2026-10-29：展示看板总ASIN替换份额指标卡

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-29（Asia/Shanghai）
- 负责人 / 集成人：本次Codex会话
- 用户目标及验收条件：样本份额指标卡改成筛选后的总ASIN，与活跃ASIN对比；同范围、按商品去重，包含零销量及缺失记录商品，多月不重复计数。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点
- 本次负责的文件或模块：看板计算、指标卡、对应导出与验证。
- 公共文件协调 / 依赖任务：主工作树串行修改，保留全部既有修改与暂存区。
- 交付方式：本地源码与dist/PM Stack.exe更新，旧EXE保存在本任务恢复目录的previous/；未提交、未推送。

## 当前现场

- 已完成：总ASIN计算、指标卡提示及Excel导出同步替换，文档与自检更新；定向38项通过，全量506项中502通过、2项符号链接权限跳过、2项DPAPI测试在沙箱失败，正常用户环境复测2项全部通过。
- 未完成 / 已知问题：本次更新已完成；用户真实工作簿效果待使用验收。未生成新分发ZIP，未发布远端。
- 未提交修改与未跟踪文件：本任务文件见下；原有修改保留。
- 已提交但未共享的内容：无本次提交。
- 恢复位置：.runtime-local/dashboard-total-asins-20261029/保存变更前文件与暂存区快照。

## 决策及原因

- 总ASIN与活跃ASIN使用同一detail范围，响应月份、站点、属性、价格与关注品牌；按ASIN去重。替换指标及导出，品牌排名和趋势中的份额仍服务原图表。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-29 / D:\PM Stack\PM Stack / main / 7245d83。
- 未提交被测代码：实施前快照和baseline-index.patch位于恢复位置；source-sha256.json记录本次6份源码/测试/说明的最终指纹。
- 命令：`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_dashboard.DashboardDataTests.test_total_asins_include_zero_and_missing_units_and_deduplicate_months --timeout 120`（实施前失败）；`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_dashboard tests.test_dashboard_import --timeout 240`；`.venv-review/Scripts/python.exe tools/run_tests.py --timeout 600`；正常用户环境`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_hotfixes.ConfigSecurityTests --timeout 120`。
- 解释器及必要环境：.venv-review，项目隔离测试入口。
- 结果：新增测试实施前预期失败（缺少总ASIN），日志tests-20261029-152952-763711.log；实施后定向38项通过，日志tests-20261029-153113-029634.log；全量日志tests-20261029-153248-657940.log（502通过、2跳过、1失败1错误）；DPAPI独立复测2项通过，日志tests-20261029-153503-503182.log。日志均位于.runtime-local/test-logs/。
- 原因：验证零销量、销量缺失、多月去重、品牌与ASIN筛选、空结果、指标卡及导出。
- 已有失败 / 本次新增失败 / 验证局限：全量中的test_secret_round_trip_has_no_plaintext_at_rest（WinError2）与test_legacy_plaintext_is_migrated_in_place仅在沙箱账户失败；正常用户上下文原样复测通过，未修改安全代码。2项符号链接权限跳过。

- 构建：过滤本进程PATH内Poppler/图像工具DLL路径后，`.venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/dashboard-total-asins-20261029/candidate --workpath build/free-matrix-rollback-20261029 "PM Stack v1.11.5.spec"`，退出0；build.log位于任务恢复目录。
- 包验证：`.venv-review/Scripts/python.exe .runtime-local/dashboard-total-asins-20261029/verify_candidate.py`退出0；87份内嵌源码、55个编译模块及main与当前文件一致，启动/矩阵、看板和销量处理三类EXE自检全部通过。package-verification.json及各自报告和截图保存在任务恢复目录；目视检查dashboard-light.png，中文清晰且总ASIN为整数。
- 安装：用户明确回复已关闭后复查无运行中程序，备份旧EXE并原子替换dist/PM Stack.exe，SHA256为50ee80758e36fed100ff96c2547e5f76bdc2d0c8ca84b8c004acc02d8e1b2268；见delivery.json。

## 接手后的第一步

1. 已完成，可重新启动dist/PM Stack.exe验证真实工作簿；总ASIN与活跃ASIN按同一筛选与关注品牌范围显示。

## 变更文件

- `handoffs/2026-10-29-dashboard-total-asins.md`
- `CURRENT.md`
- `core/dashboard_data.py`
- `modules/display_dashboard.py`
- `core/dashboard_smoke.py`
- `tests/test_dashboard.py`
- `tests/test_dashboard_import.py`
- `docs/展示看板使用说明.md`

## 收工检查

- 收工handoff check通过（73项变更、13份有效记录），baseline-index.patch与final-index.patch逐字节一致，原暂存区保留。
