# 展示看板以商品主表确定样本

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-11-16（Asia/Shanghai）
- 负责人 / 集成人：本次 Codex 会话
- 用户目标及验收条件：以商品主表确定分析样本，按 ASIN 读取历史销量和销额。验证历史表中的额外 ASIN 可以直接导入，主表商品缺失的历史指标保留空值。
- 工作目录（绝对路径）：`D:\PM Stack\PM Stack`
- 分支 / 起点 HEAD / 当前 HEAD：`main` / `ff8775b` / 发布源码提交 `053c94565d6e2f6f4dbe1c8e80a6d6e1327e037e`
- 本次负责的文件或模块：展示看板历史导入、回归测试和使用说明。
- 公共文件协调 / 依赖任务：主项目当前无其他看板源码修改。保留已有评论分析文件和索引记录。
- 交付方式：本地源码和程序，GitHub v1.11.9 正式发布。

## 当前现场

- 已完成：按主表对齐两张历史表，用原工作簿通过导入与 30 个月细分趋势核对。本地 `dist/PM Stack.exe` 已更新到 v1.11.9，GitHub 同版本已设为 latest。
- 未完成 / 已知问题：无。已打开的旧窗口需要重启以加载本地新版。
- 未提交修改与未跟踪文件：具体范围见变更文件。开工时索引有修改，另有评论分析的未跟踪文件。
- 已提交但未共享的内容：无。
- 恢复位置：本任务工作树与此记录。v1.11.9 本地替换前的程序保存在 `.runtime-local/release-v1.11.9/install/PM Stack.previous.exe`。

## 决策及原因

- 先添加历史表含样本外记录、主表商品缺历史的回归测试，再调整关联与导入说明，最后复测真实工作簿。
- 两张历史表按商品主表 ASIN 对齐。主表商品是分析样本，历史月份由来源表头确定，匹配到的销量与销额独立读取。无记录的指标保留缺失。
- 审查发现 Excel 可能对不同子表的纯数字 ASIN 推断出不同类型。导入按文本读取 ASIN，保留前导零，并让数值单元格中的商品编号一致匹配。
- 发布版本递增到 v1.11.9，现有客户端可识别更新。发布附件包括 EXE、首次分发 ZIP 和更新清单。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-11-16 / 主项目 / `main` `ff8775b`。
- 未提交被测代码（Git blob 缩写）：`dashboard_data.py` 409ae92、`dashboard_import.py` c47bf29、`dashboard_research_check.py` 55446a0、两份测试文件分别为 20e82fc、f118678。
- 命令：使用主项目 .venv-review 运行 `python tools/run_tests.py tests.test_dashboard tests.test_dashboard_import tests.test_dashboard_chart --timeout 120`、`python tools/run_tests.py --timeout 240`、`python tools/run_tests.py tests.test_hotfixes.ConfigSecurityTests --timeout 60`。另在隔离路径运行 `python -B main.py --dashboard-research-check`，参数为原工作簿与报告路径。
- 解释器及必要环境：主项目 `.venv-review`。
- 结果：新增场景先按预期失败，修复后看板专项 44 项通过（tests-20261116-104020-576122.log）。全量 516 项中 512 项直接通过、2 项权限跳过、2 项 DPAPI 沙箱失败（tests-20261116-104044-862792.log），DPAPI 项在正常 Windows 用户环境复测均通过（tests-20261116-104338-608918.log）。测试日志位于 `.runtime-local/test-logs`。
- 补充回归：数字 ASIN 用例的两个输入先复现丢失编号或销量（tests-20261116-105055-158470.log），固定 ASIN 文本读取后看板专项 45 项通过（tests-20261116-105152-839775.log）。
- 最终全量：517 项中 513 项直接通过、2 项权限跳过、2 项 DPAPI 沙箱失败（tests-20261116-105153-086498.log），DPAPI 项在正常环境复测通过（tests-20261116-105600-101071.log）。
- v1.11.9 发布回归：正常 Windows 用户环境运行 `python tools/run_tests.py --timeout 240`，517 项中 514 项通过、2 项符号链接权限跳过、1 项本机桥接连接中断（tests-20261116-110615-900225.log）。设置回环地址直连后运行 `python tools/run_tests.py tests.test_extension_bridge --timeout 60`，桥接 6 项全部通过（tests-20261116-110849-103821.log）。
- v1.11.9 程序和 ZIP 已生成，ZIP 内容集合与完整性验证通过。候选 EXE SHA-256 为 `e49a07e838efe112267775dba5d5b79a061e0fe653a54a2dc3309177b7656d0f`，对应 `update.json`。
- 发布包通过内嵌源码一致性、启动、看板和销量处理自检。真实工作簿在 v1.11.9 EXE 中导入、筛选和矩阵联动均通过，报告位于 `.runtime-local/release-v1.11.9/research-check/research.json`。
- 发布提交的 [GitHub Actions](https://github.com/Song-wenpeng/PM-Stack/actions/runs/43796579412) 成功。Release 446565767 的三个附件均重新核对服务器摘要，tag 指向上述源码提交。公开 ZIP、更新清单均返回 HTTP 200，公开清单哈希一致。
- 从公开更新通道读取 v1.11.9 并下载验证 EXE，随后使用正式更新器为隔离的 v1.11.8 副本完成替换和重启，备份与原 v1.11.8 哈希一致。证据位于 `.runtime-local/release-v1.11.9/auto-update-check/result.json`。
- 真实工作簿：隔离源码自检的报告在 `.runtime-local/dashboard-master-sample/source-check/research.json`。导入后保留商品主表的所有 ASIN。另使用两张历史表独立汇总细分条件的销量和销额，与看板完整历史期间各月趋势一致。源工作簿的 SHA-256 校验一致。
- 本地 EXE：以现有 v1.11.8 规格干净构建。87 份内嵌源码、55 个编译模块和入口与当前源码一致。启动、看板和销量处理自检通过。真实工作簿的 EXE 自检也通过，日志和报告位于 `.runtime-local/dashboard-master-sample` 的 `verify-delivery-final.log` 和 `exe-check-delivery/research.json`。验证后的 EXE 与实际交付文件 SHA-256 均为 `2f7601ada3021a3454f63ec9a2724014b140b6e4ce6da7133527237f59e89a5c`。
- 已有失败 / 本次新增失败 / 验证局限：构建缓存曾导致包内旧自检，干净构建后已核验一致。首次与真实工作簿自检并行运行时，看板自检进程退出 3221226505，随后用独立数据目录串行复测通过。未做正式用户配置下的实屏交互验证。

## 接手后的第一步

1. 使用本地 `dist/PM Stack.exe`，或从 [v1.11.9 发布页](https://github.com/Song-wenpeng/PM-Stack/releases/tag/v1.11.9) 下载后直接导入原工作簿。

## 变更文件

- `core/dashboard_data.py`
- `core/dashboard_import.py`
- `core/dashboard_research_check.py`
- `tests/test_dashboard.py`
- `tests/test_dashboard_import.py`
- `docs/展示看板使用说明.md`
- `core/main_window.py`
- `main.py`
- `PM Stack v1.11.9.spec`
- `README.md`
- `update.json`
- `CURRENT.md`
- `handoffs/2026-11-16-dashboard-master-sample.md`

## 收工检查

- 开工 status、工作树 check 与发布暂存 check 已运行。发布提交仅纳入本任务文件，源码和 Release 均已推送。
