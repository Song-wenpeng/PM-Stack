# PM Stack

面向跨境电商运营与产品研究的 Windows 桌面工作台，基于 Python / PyQt6，提供评论分析、销量数据、产品矩阵和市场规划四个模块。

当前版本：**v1.10.20**（2026-10-19）。

- [下载最新版本](https://github.com/Song-wenpeng/PM-Stack/releases/latest)
- [本阶段更新说明：v1.10.3 → v1.10.20](阶段更新说明-v1.10.20.md)
- [完整更新日志](软件更新日志.md)
- [发布与自动更新指南](发布更新指南.md)

## 功能

| 模块 | 当前能力 |
|---|---|
| 评论分析 | Excel 导入及 Amazon 评论采集、本地评论库、品类与提示词管理、逐条标签提取与汇总报告、分析记录与断点续跑 |
| 销量数据 | 单文件与批量拆分、销量/销额修正、历史数据提取、交叉属性趋势与品牌/类别份额 |
| 产品矩阵 | 场景图片矩阵、销额透视、品牌×分类矩阵、自由组合矩阵与导出 |
| 市场规划 | 文本及图片字段提取、商品资料补抓、标签筛选、字段模板、机会得分与类目筛选 |

顶部导航使用 `Ctrl+1~4` 切换模块，支持明暗主题、文件拖入、可搜索的工作表/列名选择、固定底部任务栏和结果入口。自适应图表实验模块已从当前运行版本移除。

## Windows 使用

首次使用下载 Release 的分发 ZIP，解压后保持以下文件同级，再运行 `PM Stack.exe`：

```text
PM Stack.exe
PM Stack Updater.exe
update-channel.json
```

GitHub 上的独立主程序附件使用 `PM-Stack.exe`；手动升级时关闭软件，将其重命名为 `PM Stack.exe` 后替换。自动更新由更新清单定位附件，并校验大小与 SHA-256 后替换。

在顶部右侧“设置”填写模型服务地址、API Key 和模型名称。AI 分析需要用户自己的模型服务配置；销量清洗与普通表格处理不需要模型调用。

视觉专用密钥和服务地址留空时复用通用配置；视觉模型留空且没有环境变量覆盖时，字段提取默认使用 `Qwen/Qwen3-VL-30B-A3B-Instruct`。文本模型与视觉模型分别调用。配置也可从运行环境继承，因此设置框为空不一定意味着禁用视觉调用。

API Key 使用 Windows DPAPI 加密，保存在 `%LOCALAPPDATA%\PM Stack\config.json`，不随源码、EXE 或新备份分发。换电脑后需重新填写密钥。

## 评论分析与本地备份

默认流程是“添加评论 → 选择品类 → 开始分析”，每个文件独立生成报告；评论库可以筛选评论后直接分析。分析任务保留输入与模板快照，失败、停止后可继续；提取未全部成功时不进入汇总。

评论主库使用本地 SQLite，当前版本不运行云端登录或自动同步。原云端模块、迁移 SQL 与测试保留在 [未来开发方向/云端同步](未来开发方向/云端同步/README.md)，不参与当前打包。

“评论分析 → 设置 → 数据与备份”支持完整 ZIP 备份、每日空闲自动备份、校验、保留策略和下次启动恢复。备份包括评论库、分析任务、模板与已生成报告，排除模型密钥及登录会话。销量和矩阵的外部工作簿不在此备份范围内。详见 [本地备份与恢复说明](本地备份与恢复说明.md)。

## 字段提取与续跑

1. 选择包含当前已有结果的商品 `.xlsx`，选择类目和本次提取字段。
2. 如只处理“打标 = 1”，勾选“仅提取指定标签的行”并填写标签条件；仅在 Excel 中筛选可见行不会限定程序范围。
3. 程序恢复有效断点中的字段值，保留输入表中已有有效值和人工修改，再检查本次所选字段。
4. 所选字段完整的产品跳过 AI 和网页补抓；其余产品只补缺失字段。五点描述或图片缺失时，可按商品链接自动补抓。
5. 本轮处理后仍有缺失的行标记为“未完整”并保留断点，下次继续补缺，同次运行不会无限重复排队。旧版误记为“成功”的未完整断点也会重新检查。

写回保留工作簿原行位置、普通嵌入图片、样式与支持范围内的公式；提取记录放入“字段提取日志”工作表。含复杂表格、合并单元格、命名区域或图表等结构的工作簿会先做兼容性校验。

`.checkpoint.json` 是提取断点，`.fetch_checkpoint.json` 是商品资料缓存。保存时先写 `.pending-*.xlsx`，再替换正式输出；写回受阻时会保留临时结果。操作说明和限制见 [本阶段更新说明](阶段更新说明-v1.10.20.md)。

## 源码运行

建议使用 Python 3.12+。在项目目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup_review_env.ps1
.\.venv-review\Scripts\python.exe main.py
```

也可运行 `start-pm-stack.bat`。依赖见 `requirements.txt`，构建约束见 `requirements-review.lock.txt`。Amazon 采集使用 Playwright 控制系统 Edge；商品补抓默认在后台运行，验证码、页面不可访问或加载超时均可能导致补抓失败。

## 测试与打包

```powershell
.\.venv-review\Scripts\python.exe tools/run_tests.py --timeout 240
.\.venv-review\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist --workpath build "PM Stack v1.10.20.spec"
.\.venv-review\Scripts\python.exe -m PyInstaller --noconfirm "PM Stack Updater.spec"
```

主程序输出固定为 `dist/PM Stack.exe`。`tools/build_review_fix.ps1` 会准备环境并构建同一路径。测试在隔离目录中执行；Windows 密钥存储检查需要可用的 DPAPI 用户上下文。

v1.10.20 本阶段发布前完整测试：**230 项通过**；已验证打包 EXE 启动、矩阵预览、提示词编辑器及内嵌修复代码一致性。

## 目录

```text
main.py                         应用入口
core/                           框架、表格写回、任务状态与评论服务
modules/                        四个内置功能模块
scripts/                        数据处理、模型提取与报告脚本
browser-extension/              评论采集扩展
tests/                          当前版本回归测试
tools/                          环境、构建、测试与发布工具
assets/app_icon.ico             应用图标
未来开发方向/云端同步/          非运行的云端技术归档
```

`config.json`、用户数据库、迁移数据、虚拟环境、构建日志、临时表格和展示产物不纳入源码发布。外部插件仍可通过 `plugins/modules/` 和 `plugins/scripts/` 加载。
