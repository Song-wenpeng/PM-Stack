# 2026-10-28：审查修复第三批——任务退出、配置恢复与安全保护

## 接手信息

- 状态：待确认
- 更新日期与时区：2026-10-28（Asia/Shanghai）
- 负责人 / 集成人：本次 Qoder 主会话直接实施并自证；用户已明确选择「整批做完，含关窗生命周期」，验收决定仍归用户。
- 用户目标及验收条件：按合并审查路线修 A 报告 R05、R07、R09、R10 与报告 B 的模块容错问题。关窗与更新退出不再直接杀掉正在保存的后台任务；损坏的配置不再阻止启动且不丢用户原文件；模块导入或 Widget 构造失败只影响该模块并明确告知用户；评论备份不再携带本机配对凭据，恢复也不会把别机凭据带进来；视觉模型留空时的实际生效值与界面文案一致。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点，本批不提交故 HEAD 未变
- 本次负责的文件或模块：脚本执行器与主窗口生命周期、配置管理器、评论备份凭据处理、视觉模型默认值与设置界面文案、类目脚本停止信号兼容；精确路径见「变更文件」。
- 公共文件协调 / 依赖任务：core/main_window.py 与 core/runner.py 属项目规则中的公共范围，当前无其他任务并行修改，本批为唯一写入者。第一、二批成果保持未提交；本批会小幅改动第一批的类目脚本（增加通用停止信号兼容）与第二批的机会得分 tab 所在文件（清理停止信号文件），均在「变更说明」中逐项标注。CURRENT.md 由主会话独占维护。不操作研究工作树。
- 交付方式：同工作树串行实施，不暂存、不提交、不推送、不打包、不发布。

## 当前现场

- 已完成：
  - R05：MainWindow 新增 closeEvent 与 _confirm_exit_while_running。检测到任务在跑时给出四个明确选项——等待完成、请求停止并等待保存、强制退出（文案直接写明可能丢数据）、取消；只有前两条走协作停止与有界等待，等待超时或被放弃都不关闭主窗口。更新安装退出（_start_app_install）走同一确认，不再用 QTimer 直接 quit 绕过任务保存。
  - R05 配套：ScriptRunner 为每次 run_script 创建并导出统一的 PM_STACK_STOP_FILE、登记到类级注册表，新增 request_stop_all 只写信号文件（不终止线程）与 wait_until_idle 有界等待；运行结束在 finally 中删除自己创建的信号文件。类目脚本同时认 CATEGORY_STOP_FILE 与 PM_STACK_STOP_FILE，第一批 UI 停止按钮行为不变；市场规划模块在完成回调中清理自己创建的信号文件，解决第一批遗留的累积问题。
  - R07：ConfigManager 读取每个配置来源时捕获 OSError/ValueError/TypeError，损坏文件改名隔离为 config.json.corrupt-时间戳 并保留原始字节，用默认配置启动并把原因计入警告；连续损坏不会撞名。get_warnings 此前全项目从未被调用，现在启动后与模块加载失败一起汇总告知用户。
  - 模块容错：_load_modules 对 widget_cls(...) 加保护，单个模块构造失败只跳过该模块并回收其 runner，其余模块照常加载；_scan_module_dir 的导入失败除 print 外同时记入 _module_failures。
  - R09：extension_pairing_token 加入备份排除清单；新增 scrub_credentials，恢复时在暂存数据库落回本机之前删除凭据类设置，因此修复前生成的旧备份也不会把别机凭据带进来。桥接在凭据缺失时自动重新生成并重新配对，已由测试验证。
  - R10：DEFAULT_VISION_MODEL 收敛到 core/config_manager.py，get_env_dict 始终导出 MODEL_VISION，新增 effective_vision_model；设置界面文案改为明确说明 Key 与 Base URL 留空才继承上方、模型留空使用内置默认视觉模型而非继承文本模型，占位符显示真正生效的模型名。
  - 附带修复（实施中发现）：项目根目录存在 update-channel.json，源码模式下 get_data_dir 返回项目根，导致任何构造 MainWindow 的测试都会对 GitHub 发起真实更新检查；tests/support.py 现在在沙箱用户配置中默认关闭两项自动检查。ApplicationUpdater 的后台线程在窗口销毁后 emit 会抛 RuntimeError 到线程外，已改为经 _emit 容错。
  - 定向回归 35 项通过，全量隔离回归 471 项通过、2 项因 Windows 符号链接权限跳过；协作检查通过。
- 未完成 / 已知问题：打包版 EXE 的更新器替换与重启链路、真实浏览器扩展配对、真实模型 API 与实屏 GUI 未验证；关窗等待逻辑以注入式假询问与假等待函数验证决策分支，未模拟真实长任务；R08 小屏几何、R11 自由矩阵 GUI 线程读取、插件 ZIP 校验与整体回滚、任务状态可视化与表单分层等体验项不在本批范围。
- 未提交修改与未跟踪文件：第一、二、三批成果均未暂存未提交；暂存区经字节比对与第一批开工基线一致（staged_area_identical_to_batch1_baseline=true）。
- 已提交但未共享的内容：本批无提交。
- 恢复位置：.runtime-local/review-fixes-20261028-batch1/ 与 batch2/ 为前两批只读依据；.runtime-local/review-fixes-20261028-batch3/final-sha256.json 为本批 11 个文件指纹、暂存区比对、第二批文件逐项未变确认及日志索引，final-status.txt 为当时 Git 状态。均为只读依据，不授权恢复或重置现场。

## 决策及原因

- 2026-10-28：关窗时不直接退出，也不静默杀线程。检测到任务在跑时给用户三个明确选项：等待完成、请求安全停止并等待保存、强制退出（文案直接写明可能丢数据），外加取消。原因是 daemon 线程在解释器退出时被硬终止，脚本没有机会执行 finally 与断点保存，而强制退出在用户知情时仍是必要逃生口。
- 2026-10-28：安全停止走协作信号文件而不是线程终止。ScriptRunner 为每次运行导出统一的 PM_STACK_STOP_FILE 并登记，关窗时只写信号文件再等待执行锁释放；类目脚本同时认 CATEGORY_STOP_FILE 与 PM_STACK_STOP_FILE，保持第一批 UI 停止按钮行为不变。
- 2026-10-28：等待过程用可取消的模态进度提示并设上限，超时不关闭主窗口而不是强行退出，避免「等太久」退化成「丢数据」。
- 2026-10-28：更新安装退出前走同一套确认，修掉「更新退出绕过任务保存」这条独立路径。
- 2026-10-28：运行结束时由 ScriptRunner 删除自己创建的停止信号文件，顺带解决第一批遗留的信号文件在状态目录累积问题；UI 自己创建的停止文件也在完成回调中清理。
- 2026-10-28：坏配置不阻止启动，但也不静默丢弃。读取失败时把损坏文件改名隔离为 .corrupt-时间戳，保留用户原始字节以便修复，再用默认配置启动并把原因计入警告；启动后统一向用户展示警告，因为 get_warnings 此前从未被调用，等于警告写了没人看。
- 2026-10-28：选择隔离改名而不是原地忽略，因为后续任何一次 save() 都会用默认配置覆盖原文件，用户的原始内容会无声消失。
- 2026-10-28：模块导入失败与 Widget 构造失败都只跳过该模块并记录，主窗口照常启动；失败清单在启动后一次性告知用户，而不是只 print 到看不见的控制台。
- 2026-10-28：extension_pairing_token 加入备份排除清单，且恢复时在落盘前从暂存数据库中删除凭据类设置，这样旧备份里已存在的凭据也不会被带回本机；桥接在凭据缺失时会自动重新生成并重新配对，因此清除是安全的。
- 2026-10-28：视觉模型默认值收敛到 core/config_manager.py 的 DEFAULT_VISION_MODEL，get_env_dict 始终导出 MODEL_VISION，界面文案改为明确说明 Key 与 Base URL 留空才继承上方、模型留空使用内置默认视觉模型而不是继承文本模型；并加一条测试断言两个提取脚本内的硬编码默认值与 core 常量一致，防止再次漂移。
- 2026-10-28：不把上方文本模型当作视觉模型回退，因为 deepseek-ai/DeepSeek-V3 不支持图片输入，继承只会让图片识别静默失败；文案与实际保持一致比「看起来更聪明」的回退更安全。
- 2026-10-28：计划外多改两个文件，均属实施中发现的既有缺陷且与本批主题同源，故就地修掉而不另开批次。core/app_updater.py 的后台线程在窗口销毁后 emit 会抛 RuntimeError 到线程外，本批关窗保护会让这种「窗口先没、线程后结束」的时序更容易出现，因此加 _emit 容错属于本批必要配套。tests/support.py 此前没有关闭自动更新检查，源码模式下 get_data_dir 返回项目根而项目根存在 update-channel.json，导致任何构造 MainWindow 的测试都对 GitHub 发真实请求；这与「测试必须隔离、禁真实请求」的既有约束冲突，属隔离层缺陷，修在隔离层而不是生产代码。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-28 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 未提交被测代码指纹：本批 11 个文件 SHA-256 见 .runtime-local/review-fixes-20261028-batch3/final-sha256.json；其中 batch2_files_verified_unchanged 以第二批指纹逐项比对，确认 product_matrix2.py、机会得分.py、report_io.py 及第二批三份测试本批未被改动，batch2_files_changed_by_batch3 只有 modules/market_planning.py（清理停止信号文件一处）。暂存区与第一批开工基线字节一致，本批未暂存任何改动。
- 命令：定向 `.venv-review/Scripts/python.exe tools/run_tests.py tests.test_app_lifecycle tests.test_config_recovery tests.test_backup_credentials --timeout 300`；全量 `.venv-review/Scripts/python.exe tools/run_tests.py --timeout 600`；协作检查 `python tools/handoff.py status --repo "D:/PM Stack/PM Stack"` 与 `python tools/handoff.py check --repo "D:/PM Stack/PM Stack"`。
- 结果：定向 Ran 35 tests OK 退出码 0（tests-20261028-153837-028270.log），其中生命周期用例首轮单跑 15 项通过（tests-20261028-153141-988067.log）；全量 Ran 471 tests OK skipped=2 退出码 0（tests-20261028-153914-378412.log），较第二批全量 436 项净增 35 项。
- 覆盖点：无任务时关窗直接放行且不弹询问；取消与等待未结束都不关闭窗口；强制退出不等待即放行；等待完成不发停止信号；请求停止会写协作信号并等待；更新安装在守卫拒绝时既不启动更新器也不读取清单，守卫放行时才继续；停止信号注册表写入后可被脚本读到、释放时文件被清理；真实 run_script 导出 PM_STACK_STOP_FILE，脚本读到信号后先写「已安全保存」标记再退出，wait_until_idle 返回真且执行锁释放；执行锁被占用时 wait_until_idle 超时返回假；单个模块 Widget 构造抛异常时其余五个内置模块照常加载、栈页数与 runner 数与成功模块数一致、失败被记入清单；模块导入失败被记录而不只 print；启动问题汇总同时包含模块失败与配置警告，干净启动不弹窗。配置端覆盖坏 JSON、JSON 类型错误、路径是目录三种损坏形态都能启动并隔离原文件且字节保留、缺失文件不产生警告、合法配置无警告、恢复后 save 写出合法配置且隔离文件不被覆盖、连续两次损坏不撞名。视觉模型端覆盖留空与纯空白回落到内置默认、显式值被导出、不继承文本模型、core 默认值与两个提取脚本内硬编码默认值一致（防漂移）、设置界面占位符显示生效模型且旧的误导文案已移除。备份端覆盖新备份的暂存数据库不含配对令牌但保留其他设置与评论数据、scrub_credentials 只删凭据、无 settings 表的旧库不报错、按修复前排除清单伪造的旧备份确实含令牌且恢复后本机不再有该令牌而评论数据完整恢复、桥接在凭据被清除后重新生成新令牌。
- 解释器及必要环境：.venv-review/Scripts/python.exe（CPython 3.12.14）；tools/run_tests.py 有界子进程隔离加 tests/support.py 沙箱；QT_QPA_PLATFORM=offscreen；沙箱用户配置默认关闭两项自动更新检查，全量回归无外网请求；无真实模型调用，无真实浏览器扩展。
- 原因：本批改动全局退出路径、配置装载与备份内容，影响面覆盖整个应用，历史通过记录不能替代当前证据，故跑定向与全量回归；并以跨批指纹比对证明前两批成果未被意外改动。
- 已有失败 / 本次新增失败 / 验证局限：本批无新增失败。全量 2 项跳过为历史已知的 Windows 符号链接权限限制，非本批引入。实施中发现并修复了两个既有缺陷：源码模式下测试会对 GitHub 发起真实更新检查（项目根存在 update-channel.json 且 get_data_dir 返回项目根），以及 ApplicationUpdater 后台线程在窗口销毁后 emit 抛 RuntimeError；前者已在隔离层关闭，后者已在生产代码容错。打包版 EXE 的实际更新器替换与重启、真实扩展配对、实屏 GUI 手动关窗未授权验证，故关窗体验仍为待确认。

## 接手后的第一步

1. 等待用户对第一、二、三批的验收决定。获授权后按第四批范围处理 R08（小屏初始几何可能超出可用区域、位置未含屏幕原点）、R11（自由矩阵读表与渲染在 GUI 线程）、插件 ZIP 的 sha256 与签名校验及整体回滚、任务状态可视化与表单分层等体验项，不夹带本批文件以外的改动。

## 变更说明

以下为各文件改动要点，供复核使用；精确文件范围声明见其后的「变更文件」节。

- core/runner.py：新增停止信号登记与 PM_STACK_STOP_FILE 导出、request_stop_all 协作停止、wait_until_idle 有界等待，运行结束清理自己创建的信号文件；不改动执行锁语义与 runpy 执行路径。
- core/main_window.py：新增 closeEvent 与 _confirm_exit_while_running、_ask_exit_choice、_block_until_idle；更新安装退出前走同一确认；_load_modules 对 Widget 构造加保护并记录失败；_scan_module_dir 收集失败而不只 print；启动后统一展示模块失败与配置警告；设置界面视觉模型文案与占位符改为反映实际生效值。
- core/config_manager.py：load 对各配置来源加容错并隔离损坏文件、保留原始字节、计入警告；新增 DEFAULT_VISION_MODEL 与 effective_vision_model；get_env_dict 始终导出 MODEL_VISION。
- core/reviews/backup.py：EXCLUDED_SETTINGS 增加 extension_pairing_token；新增 CREDENTIAL_SETTINGS 与 scrub_credentials，恢复时在落盘前从暂存数据库删除凭据类设置。
- core/app_updater.py：新增 _emit 静态方法，后台线程发射信号时容忍接收者已销毁；检查与下载线程及 download_update 的发射点全部改走该方法。属实施中发现的既有缺陷修复，不改变更新判定、下载校验与清单语义。
- scripts/欧洲市场规划/类目初筛.py：停止信号同时认 CATEGORY_STOP_FILE 与 PM_STACK_STOP_FILE，其余逻辑不动（第一批文件，本批仅此一处兼容性改动，指纹已单独核对）。
- modules/market_planning.py：类目完成回调清理本模块创建的停止信号文件，解决第一批遗留的信号文件累积（第二批文件，本批仅此一处改动）。
- tests/support.py：沙箱用户配置默认写入 auto_check_app_update 与 auto_check_update 为 False。属实施中发现的测试隔离缺陷修复：项目根存在 update-channel.json 且源码模式 get_data_dir 返回项目根，此前任何构造 MainWindow 的测试都会对 GitHub 发起真实更新检查。单个测试仍可覆盖这两个开关。
- tests/test_app_lifecycle.py：新增 15 用例，覆盖关窗与更新退出的决策分支、协作停止只写信号不杀线程、真实 run_script 的停止信号端到端、等待超时、模块导入与 Widget 构造失败隔离、启动警告汇总。
- tests/test_config_recovery.py：新增 13 用例，覆盖坏配置三种形态的恢复与隔离、原始字节保留、恢复后可正常保存、视觉模型默认值与 env 导出、与两个提取脚本硬编码默认值一致、设置界面文案。
- tests/test_backup_credentials.py：新增 7 用例，覆盖新备份排除凭据、其他数据不受影响、scrub 幂等与旧库容错、旧备份恢复后凭据被清除、桥接重新生成令牌。
- .runtime-local/review-fixes-20261028-batch3/ 与 .runtime-local/test-logs/ 为 gitignore 运行期证据，不作为提交源码列出。

## 变更文件

- `CURRENT.md`
- `handoffs/2026-10-28-review-fixes-batch3.md`
- `core/app_updater.py`
- `core/config_manager.py`
- `core/main_window.py`
- `core/reviews/backup.py`
- `core/runner.py`
- `modules/market_planning.py`
- `scripts/欧洲市场规划/类目初筛.py`
- `tests/support.py`
- `tests/test_app_lifecycle.py`
- `tests/test_backup_credentials.py`
- `tests/test_config_recovery.py`

## 收工检查

- 实施、定向与全量回归、跨批指纹与暂存区比对均已完成，状态置「待确认」，等待用户验收；未宣布最终验收完成，未进入第四批。
- 收工协作检查 `python tools/handoff.py check --repo "D:/PM Stack/PM Stack"` 返回 Handoff check passed: 59 change(s), 9 record(s)，退出码 0；开工时另执行 `python tools/handoff.py status --repo "D:/PM Stack/PM Stack"` 确认目录、分支、HEAD 与钩子位置。该结果只证明记录结构与文件覆盖合规，不代表功能验收通过。
- 全量回归之后仅修改了本记录、CURRENT.md 与 .runtime-local 证据 JSON；源码与测试指纹以 final-sha256.json 为准并已复核未变。
- 本批比计划多改了两个文件并已登记原因：core/app_updater.py 修复后台线程向已销毁对象发射信号的既有缺陷，tests/support.py 关闭测试期的真实更新检查。两者都不改变业务语义，但属公共范围，已在「变更说明」与「决策及原因」中说明。
- 不修改 AGENTS.md、Git 配置或权限，不安装依赖，不暂存、不提交、不推送、不打包、不发布，不调用真实模型 API。
