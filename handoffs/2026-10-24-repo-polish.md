# 仓库主页完善：推送、根目录整理与 About 侧栏

## 接手信息

- 状态：已完成（About 侧栏更新结果见“验证证据”）
- 更新日期与时区：2026-10-24（Asia/Shanghai）
- 负责人 / 集成人：ZCode 会话（用户授权执行全部三项）
- 用户目标及验收条件：完善仓库主页的三项建议——①推送 v1.11.x 提交解决内容滞后；②根目录 spec/文档整理且不破坏发布工具链；③补全 GitHub About 侧栏（描述与 topics）。
- 工作目录（绝对路径）：`D:\PM Stack\PM Stack`
- 分支 / 起点 HEAD / 当前 HEAD：`main` / `1d4de2a` / 见下方提交记录
- 本次负责的文件或模块：根目录 spec 与说明文档、`publish.py`、`README.md`、`软件更新日志.md`、`CURRENT.md`、本记录
- 公共文件协调 / 依赖任务：无；研究工作树未改动
- 交付方式：同工作树直接提交并推送

## 当前现场

- 已完成：
  1. 推送此前两个提交到 GitHub（`186c2dc..1d4de2a`，2026-10-24），远端 README 已更新为 v1.11.5 五模块。
  2. `git mv` 归档 24 份历史 spec（`PM Stack V1.10.2.spec`、v1.10.3～v1.10.20、v1.11.0～v1.11.4）至 `specs/archive/`；根目录仅保留 `PM Stack Updater.spec` 与 `PM Stack v1.11.5.spec`（当前生效，`tools/build_review_fix.ps1` 与 README 打包命令引用的就是它们，未变）。
  3. `git mv` 7 份说明文档至 `docs/`：展示看板使用说明、本地备份与恢复说明、发布更新指南、阶段更新说明-v1.10.20、GitHub附件上传失败问题、产品信息提取改进方案-2026-10-23、PM Stack 使用说明.html。`docs/` 无同名冲突。
  4. `publish.py` 适配：`RELEASE_GUIDE` 改指 `docs/发布更新指南.md`；新增 `available_spec_templates()`（根目录+归档目录、按版本号降序，替代原 mtime 取最新的 glob 逻辑）与 `archive_previous_spec()`（发布新版本时把上一版 spec 自动移入 `specs/archive/`，并 `git add -A -- specs/ <旧spec>` 纳入发布提交）。发布时根目录永远只留当前版本 spec。
  5. `README.md` 5 处链接改指 `docs/`，目录树补 `docs/`、`specs/` 两行；`软件更新日志.md` 1 处链接同步。
- 未提交修改与未跟踪文件：无（全部随本次整理提交提交）
- 未完成 / 已知问题：无
- 已提交但未共享的内容：无
- 恢复位置：本次整理提交见 `git log`；如需回退用 `git revert`，文件移动均使用 `git mv` 保留历史。

## 决策及原因

- 2026-10-24：spec 整理采用“当前版本留根目录 + 历史归档”而非全部移入 `specs/`。原因：spec 内部相对路径（`Analysis(['main.py'])` 等）按 spec 所在目录解析，整体迁移需逐份改写并重新验证 PyInstaller 行为，风险与本任务收益不成比例；归档方案不动生效文件，工具链零风险。
- 2026-10-24：`publish.py` 的 spec 模板回退选择从“mtime 最新”改为“版本号最大”。原因：归档目录内文件 mtime 不可靠，版本号排序才与“取最新模板”的语义一致。
- 2026-10-24：`阶段更新说明-v1.10.20.md` 内指向 `blob/v1.10.20/...` 的绝对链接未修改。原因：链接指向历史标签的树，移动后旧标签内路径不变，链接永远有效。

## 验证证据

- 2026-10-24 推送：`git push origin main` → `186c2dc..1d4de2a main -> main`（首次失败为网络重置，重试成功）。
- 移动前核对：`tests/` 中 `.spec` 命中均为 `importlib.util.spec_from_file_location`（模块加载 API），与打包 spec 无关；v1.11.5.spec 的 datas 仅含 `core`、`modules` 目录，不引用任何待移动文档。
- `publish.py` 修改后 `py_compile` 通过；整理后的目录上实测 `available_spec_templates()`：返回 25 份模板，最新为根目录 `PM Stack v1.11.5.spec`、最旧为归档内 `PM Stack V1.10.2.spec`，`get_current_version()` 返回 v1.11.5；`docs/发布更新指南.md` 存在、旧路径不存在。
- 引用复查：整理后 `git grep` 确认根目录文档旧路径引用仅存于 `handoffs/` 历史记录（按协议不改写历史）。
- About 侧栏：`gh repo edit` 更新描述为“跨境电商运营与产品研究桌面工作台（Python/PyQt6）：评论分析、销量数据、产品矩阵、市场规划、展示看板”，添加 topics：python、pyqt6、pyqt、ecommerce、data-analysis、desktop-app、market-research；`gh repo view` 复核描述与 7 个 topics 均已生效。

## 下一步

- 无强制后续。可选：下次发布 v1.11.6 时观察 `publish.py` 自动归档旧 spec 与发布提交是否符合预期。
