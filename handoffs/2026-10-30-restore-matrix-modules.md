# 恢复矩阵子模块及v1.11.8发布

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-30（Asia/Shanghai）
- 负责人 / 集成人：本次Codex会话
- 用户目标及验收条件：恢复昨天删除的使用场景矩阵和品牌×分类矩阵；保留自由组合矩阵新布局；沿用本次会话交付方式打包发布。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 1425a88 / 源码提交4aca8693e10d8724406d059b541620a28bbebd6e
- 本次负责的文件或模块：模块入口恢复、版本更新及应用发布。
- 公共文件协调 / 依赖任务：串行主工作树；开工无既有修改。
- 交付方式：本地dist和GitHub Release。

## 当前现场

- 已完成：恢复v1.11.6的两项完整表单及调用，默认页保留自由组合矩阵；新布局源码保持。
- 未完成 / 已知问题：无待发布事项；真实业务工作簿效果待用户使用验收。
- 未提交修改与未跟踪文件：本记录所列文件。
- 已提交但未共享的内容：无；4aca869已推送且GitHub CI成功。
- 恢复位置：.runtime-local/release-v1.11.8，模块原版本另有Git历史。

## 决策及原因

- 只恢复产品矩阵模块文件的两项功能；顶部字段库、左右分组、隐藏介绍区保留v1.11.7行为。
- 增加v1.11.8版本让客户端能检测更新。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-30 / D:\PM Stack\PM Stack / main / 1425a88。
- 未提交被测代码：当前工作区，构建后核验内嵌源码。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_matrix_layout --timeout 120；随后完整回归、PyInstaller和候选验证。
- 解释器及必要环境：.venv-review，隔离数据，offscreen Qt。
- 结果：恢复前页签断言失败、恢复入口缺失，日志tests-20261030-165308-373453.log；实施后19项定向通过；原件保护新增5项通过且独立复核通过；最终全量514项中512通过、2项权限跳过，日志tests-final.log及tests-20261030-170021-081879.log；最终构建退出0，build-final.log。
- 原因：确认恢复的页签与脚本调用实际可用，且新布局不回退。
- 已有失败 / 本次新增失败 / 验证局限：真实业务工作簿待使用验收。

## 接手后的第一步

1. 无待发布步骤；可直接运行dist/PM Stack.exe或下载v1.11.8分发包。

## 变更文件

- `modules/product_matrix.py`
- `core/main_window.py`
- `main.py`
- `README.md`
- `tests/test_matrix_layout.py`
- `tests/test_hotfixes.py`
- `tests/test_task_interaction.py`
- `PM Stack v1.11.8.spec`
- `update.json`
- `CURRENT.md`
- `handoffs/2026-10-30-restore-matrix-modules.md`

- `scripts/product_matrix.py`
- `scripts/product_matrix3.py`

## 收工检查

- 开工status已运行；源码提交前暂存检查通过（13项、1份记录），收工记录检查通过。

- 审查发现并复现旧模块输出可覆盖源文件，恢复时新增UI和脚本两层require_distinct保护；测试先失败，修复后继续验证。

- 最终包验证：87份源码、55个编译模块及main一致；启动、看板、销量处理三类自检退出0，verify-final.log及package-verification.json。独立复核确认防覆盖问题已解决，无其他重要发现。

- 本地安装：确认无运行中应用后备份previous/PM Stack.exe，原子替换dist主程序；ZIP和清单同步dist，release/archive/v1.11.8与release/current保留完整产物。
- EXE SHA256：130d97949859171904e45f9689394f5f5af2aec62f4d1d9878a6300de53cfad4。

- 发布完成：Release ID 428825999，v1.11.8为latest，draft=false；EXE/ZIP/update.json均上传HTTP201，服务器digest等于本地SHA256。
- 公开验证：ZIP下载HTTP200；latest更新清单重新下载哈希匹配本地。
- 项目：https://github.com/Song-wenpeng/PM-Stack
- 下载：https://github.com/Song-wenpeng/PM-Stack/releases/download/v1.11.8/PM-Stack-v1.11.8.zip
- ZIP SHA256：9c97485b684610e331b1019bb0ded5c0637872cee93c596b9381a11f006717e7。
