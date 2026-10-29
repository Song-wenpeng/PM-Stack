# 2026-10-29：商品明细复制与ASIN跳转

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-29（Asia/Shanghai）
- 负责人 / 集成人：本次Codex会话
- 用户目标及验收条件：商品明细支持复制全部字段，点击具体ASIN打开对应站点的亚马逊商品页面；保留搜索、排序及选中商品发送矩阵。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点
- 本次负责的文件或模块：明细表格、模型、矩阵选中范围及对应测试/自检/说明。
- 公共文件协调 / 依赖任务：主工作树串行实施，保留73项既有变更与暂存区。
- 交付方式：本地源码与EXE更新，不提交、不发布。

## 当前现场

- 已完成：复制、ASIN链接、指针/提示和矩阵选中范围已实施；42项定向通过，510项全量中508通过、2项权限跳过；EXE内嵌一致性和三类自检通过，已备份替换dist/PM Stack.exe。
- 未完成 / 已知问题：本地更新完成，真实业务工作簿与实际浏览器页面待用户使用验收；本轮未生成分发ZIP、未发布远端。
- 未提交修改与未跟踪文件：本任务见变更文件，其他既有改动保留。
- 已提交但未共享的内容：无本次提交。
- 恢复位置：.runtime-local/dashboard-detail-actions-20261029/保存实施前文件及暂存区。

## 决策及原因

- 单元格可选择，Ctrl+C复制选中区域，以制表符及换行支持粘贴Excel；右键可复制单元格、选中内容、所选整行。
- ASIN仅在有效10位标识和已知站点时显示链接并打开系统浏览器；使用当前行站点及ASIN构造链接，排序/搜索后仍对应同一行。Ctrl/Shift选择或拖动不触发浏览器。
- 选择单元格后发送矩阵使用涉及的行，避免selectedRows为空时误发全部商品。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-29 / D:\PM Stack\PM Stack / main / 7245d83。
- 未提交被测代码：恢复位置保存实施前文件，source-sha256.json保存5份变更源码/测试/说明指纹，baseline-index.patch与final-index.patch保存暂存区核对证据。
- 命令：`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_dashboard_detail --timeout 120`（实施前）；`.venv-review/Scripts/python.exe tools/run_tests.py tests.test_dashboard_detail tests.test_dashboard tests.test_dashboard_import --timeout 240`（实施后）。
- 解释器及必要环境：.venv-review、项目隔离测试入口与offscreen Qt。
- 结果：实施前复制断言失败且链接功能缺失，日志tests-20261029-154332-274557.log；首次41项通过后增加实际右键事件检查，暴露viewport坐标偏移（B错拷为A，tests-20261029-154525-368067.log），修复后42项全部通过，tests-20261029-154547-565876.log。日志均在.runtime-local/test-logs/。
- 原因：验证排序/搜索后复制与链接准确性，多行多列TSV及字段内换行/制表符保持，矩阵只发送涉及的商品，Ctrl多选不打开浏览器，UK/US跳转与无效标识保护。
- 已有失败 / 本次新增失败 / 验证局限：新增测试曾因mock C++方法未绑定而造成Qt测试进程退出（tests-20261029-154448-165480.log）；修正测试替身后定位并修复实际坐标错误。最终定向无失败。浏览器仅拦截openUrl验证目标，不访问真实业务文件或外部商品页面。

- 完整回归：正常Windows用户环境运行`.venv-review/Scripts/python.exe tools/run_tests.py --timeout 600`，510项中508通过、2项Windows符号链接权限跳过，无失败/错误；日志.runtime-local/test-logs/tests-20261029-154816-804285.log。
- 构建：过滤本进程PATH内Poppler/图像工具DLL路径后，`.venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/dashboard-detail-actions-20261029/candidate --workpath build/free-matrix-rollback-20261029 "PM Stack v1.11.5.spec"`，退出0，任务恢复目录build.log。

- 包验证：`.venv-review/Scripts/python.exe .runtime-local/dashboard-detail-actions-20261029/verify_candidate.py`退出0，87份内嵌源码、55份编译模块与main一致；启动/矩阵、看板（新增复制及商品URL自检）、销量处理三类自检通过。报告package-verification.json及截图位于任务恢复目录；已目视检查dashboard-detail-copy.png，ASIN下划线与单元格选择显示正常。
- 安装：用户明确回复已关闭，安装前复查无运行中应用，备份至任务恢复目录previous/PM Stack.exe后原子替换dist/PM Stack.exe，SHA256为9b9f9f166a0dca54628a7574053ce38cf5c5e4b758755adf9928e2a3cd811e92；见delivery.json。

## 接手后的第一步

1. 已完成，重新打开dist/PM Stack.exe即可使用；单元格Ctrl+C、右键复制，单击ASIN跳转，Ctrl/Shift选择。

## 变更文件

- `CURRENT.md`
- `handoffs/2026-10-29-dashboard-detail-actions.md`
- `core/dashboard_widgets.py`
- `modules/display_dashboard.py`
- `tests/test_dashboard_detail.py`
- `core/dashboard_smoke.py`
- `docs/展示看板使用说明.md`

## 收工检查

- 收工handoff check通过（76项变更、14份有效记录）；baseline-index.patch与final-index.patch逐字节一致，原暂存区未变。
