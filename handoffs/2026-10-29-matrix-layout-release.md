# 自由组合矩阵布局精简及v1.11.7发布

## 接手信息

- 状态：进行中
- 更新日期与时区：2026-10-29（Asia/Shanghai）
- 负责人 / 集成人：本次Codex会话
- 用户目标及验收条件：移除产品矩阵介绍，顶部横排字段库、左纵向右横向分组；移除使用场景及品牌分类子模块；打包上传GitHub并交付链接。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / cf09b37 / 待提交
- 本次负责的文件或模块：矩阵布局、模块入口、版本及发布。
- 公共文件协调 / 依赖任务：主工作树串行，无其他未提交修改。
- 交付方式：本地构建与GitHub v1.11.7正式发布。

## 当前现场

- 已完成：新布局测试修改前因纵排字段失败；已按用户明确布局实施。
- 未完成 / 已知问题：回归及候选构建完成，GitHub发布待完成。
- 未提交修改与未跟踪文件：本记录所列变更。
- 已提交但未共享的内容：无。
- 恢复位置：.runtime-local/release-v1.11.7/before。

## 决策及原因

- 沿用Qt及现有拖拽分组机制，只重排面板；字段显示约两行，超出垂直滚动，左右侧栏可调宽。
- 移除两项UI及处理入口；历史命令行脚本保留供兼容，销额透视保留。
- 自由组合矩阵设为默认；产品矩阵隐藏页面标题介绍区。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-29 / D:\PM Stack\PM Stack / main / cf09b37。
- 未提交被测代码：当前修改，原文件备份在恢复位置。
- 命令：tools/run_tests.py tests.test_matrix_layout；后续回归及PyInstaller构建。
- 解释器及必要环境：.venv-review，隔离数据与offscreen Qt。
- 结果：修改前布局断言失败，日志tests-20261029-233332-974051.log；修改后23项定向通过；另2项布局与入口检查通过。完整510项508通过、2项权限跳过，日志tests-20261029-233533-124784.log。候选PyInstaller构建退出0，87份源码、55个编译模块和main核对一致。三类自检复测全部退出0，见package-verification.json、verify-retry.log。首次看板自检成功保存报告后退出原生异常3221226505，复测未再现，保留为验证局限。1080×700与1440×900模拟数据界面截图已目视检查。
- 原因：验证可见布局、移除入口及原分组交互。
- 已有失败 / 本次新增失败 / 验证局限：真实工作簿待用户使用验收。

## 接手后的第一步

1. 执行回归、构建及发布。

## 变更文件

- `core/matrix_workspace.py`
- `modules/product_matrix.py`
- `core/main_window.py`
- `tests/test_matrix_workspace.py`
- `tests/test_task_interaction.py`
- `tests/test_hotfixes.py`
- `README.md`
- `main.py`
- `tests/test_matrix_layout.py`
- `PM Stack v1.11.7.spec`
- `update.json`
- `CURRENT.md`
- `handoffs/2026-10-29-matrix-layout-release.md`

## 收工检查

- 提交前及收工检查待执行。
