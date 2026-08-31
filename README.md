# PM Stack

电商数据分析工作台（PyQt6 桌面应用）—— 面向跨境电商（亚马逊）运营/产品的一站式数据分析工具，涵盖评论 VOC 分析、销量数据清洗与趋势分析、AI 智能出图、产品矩阵、市场规划五大模块。

- **明/暗双主题**：默认浅色（DeepSeek 风格），导航栏底部一键切换，选择自动记忆
- **窄图标导航栏**：悬停显示功能说明，`Ctrl+1~5` 快速切换模块
- **文件拖拽**：所有路径输入框支持从资源管理器直接拖入文件/文件夹
- **插件化架构**：`modules/` 目录下新增模块文件（含 `MODULE_INFO` + `ModuleWidget`）即自动加载，也支持 `plugins/modules/` 外部插件

---

## 功能总览与脚本对照

### 1. 评论分析（modules/comment_analysis.py）

对评论 Excel 做 AI 特征提取与归类汇总，依赖设置中的 LLM API。

| 子功能 | 说明 | 对应脚本 |
|---|---|---|
| AI 提取标签 | 逐条读取评论，AI 提取优缺点/使用场景/问题点等标签 | `scripts/comments_step_1.py` |
| 汇总洞察 | 将提取的标签按主题归类汇总，形成分析结论 | `scripts/comments_step_2.py` |
| 一键完成 | 提取 → 汇总全流程自动串联，支持中途停止 | 依次调用上述两个脚本 |
| 批量分析 | 多文件依次执行完整分析，支持停止 | 同上，模块内队列调度 |

品类模板配置：`scripts/product_configs.json`（界面支持导入/导出）。

侧边栏的“评论分析TEST”用于验证并发提取：默认并发 8，并提供 RPM/TPM
安全上限、停止、断点继续和失败补跑。Step 1 仍有失败时不会自动进入 Step 2；
断点文件保存在 Step 1 输出旁，全部成功后自动删除。验证稳定前，正式“评论分析”
仍使用串行脚本。

### 2. 销量数据（modules/sales_data.py）

| 子功能 | 说明 | 对应脚本 |
|---|---|---|
| 数据清洗 - 单文件拆分 | 单 Excel 按 ASIN/子体拆分销量 | `scripts/sales_number.py` |
| 数据清洗 - 批量拆分 | 文件夹内所有 Excel 批量拆分 | `scripts/batch_sales_split.py` |
| 数据清洗 - ASIN 趋势提取 | 按 ASIN 提取指定字段时间序列，生成数据表+趋势图 | `scripts/extract_asin_trend.py` |
| 数据清洗 - 数据修正 | 修正指定 ASIN+年月的销量/销额矫正值 | `scripts/fix_sales_data.py` |
| 交叉属性 | 1-5 个筛选条件动态组合（支持多值 `列名=值1,值2`），销量/销额/销量&均价双轴趋势图，可导出数据 | `scripts/trend_by_attribute.py` |
| 市场占比 | 按品牌/类别统计月度份额占比趋势，Top N 展示，可导出份额表 | `scripts/brand_share_trend.py` |

> 交叉属性/市场占比的「元数据Sheet」留空时默认使用 Excel 的第一个 Sheet。

### 3. 自适应图表（modules/adaptive_chart.py）

粘贴表格数据 → AI 识别结构并清洗 → 自动选择图型出图，右侧实时预览，支持打开图片/输出目录。

- AI 解析：调用设置中的 LLM API（模块内 `AIThread`，非脚本）
- 出图：`scripts/quick_chart.py`（柱状/饼图/折线/100%堆积面积/正负面积堆积/排名条形图）
- 快捷键：`Ctrl+Enter` 生成

### 4. 产品矩阵（modules/product_matrix.py）

| 子功能 | 说明 | 对应脚本 |
|---|---|---|
| 使用场景矩阵 | 按使用场景分列，嵌入商品主图+ASIN+上架时间 | `scripts/product_matrix.py` |
| 销额透视矩阵 | 双维度交叉透视（销额总和/ASIN数/平均销额），支持子表格月份取值 | `scripts/product_matrix2.py` |
| 品牌×分类矩阵 | 品牌为列、分类为行的图片矩阵，支持变体合并 | `scripts/product_matrix3.py` |

### 5. 市场规划（modules/market_planning.py）

| 子功能 | 说明 | 对应脚本 |
|---|---|---|
| 字段提取 | 从商品描述/主图用 AI 提取结构化字段（文本+视觉双通道），字段规则可编辑 | `scripts/exstract_from_description.py` |
| 机会得分 | 读取市场数据文件夹，计算细分市场综合机会得分排序 | `scripts/欧洲市场规划/机会得分.py` |
| 类目筛选 | AI 对类目列表初筛，过滤不相关/不可进入类目 | `scripts/欧洲市场规划/类目初筛.py` |
| 数据进度 | 对比全部 ID 与已爬取目录，统计各品类完成百分比 | `scripts/欧洲市场规划/数据获取进度.py` |

字段规则配置：`scripts/product_field_config.json`（界面内可添加类目、编辑字段）。

---

## 目录结构

```
PM Stack/
├── main.py                 # 入口（高DPI适配、启动主窗口）
├── updater_main.py         # 独立更新器入口（等待退出、替换、回滚、重启）
├── core/                   # 框架层
│   ├── main_window.py      # 主窗口：窄图标导航 + 标题栏 + 内容区 + 设置对话框
│   ├── theme.py            # 设计系统：明/暗双主题令牌 + QSS 生成
│   ├── icons.py            # QPainter 手绘线性图标库
│   ├── widgets.py          # 共享组件：Card / LogConsole / FileDropLineEdit 等
│   ├── runner.py           # 脚本执行器（后台线程 + 日志信号 + 环境变量注入）
│   ├── config_manager.py   # config.json 读写、脚本/插件目录解析
│   ├── app_updater.py      # 主程序清单、下载与 SHA-256 校验
│   └── updater.py          # GitHub 检查更新/下载插件包
├── modules/                # 五大内置功能模块（UI 层，不含业务逻辑）
├── scripts/                # 业务脚本（数据处理/绘图/AI 调用，模块通过 runner 调用）
├── plugins/                # 外部插件目录（modules/ + scripts/）
├── config.json             # 用户配置（API Key、主题等）
├── update-channel.json     # 可选的统一主程序更新通道
├── requirements.txt
├── PM Stack V1.10.2.spec   # 主程序 PyInstaller 配置（稳定文件名）
└── PM Stack Updater.spec   # 独立更新器 PyInstaller 配置
```

## 运行与打包

```bash
# 安装依赖
pip install -r requirements.txt

# 源码运行
python main.py

# 打包（产物输出到 dist/）
pyinstaller --noconfirm "PM Stack V1.10.2.spec"
pyinstaller --noconfirm "PM Stack Updater.spec"
```

建议使用 Python 3.12 构建和运行。当前机器实测 Python 3.9.6 / OpenSSL 1.1.1k
连接 SiliconFlow 时会在 TLS 握手阶段收到 EOF，而 Python 3.12.13 / OpenSSL 3.5.7
正常。打包前可运行 `python tools/check_llm_connection.py` 验证实际运行时，不能只用
浏览器或 `curl` 代替验证。

## 配置说明（设置对话框）

| 配置项 | 用途 |
|---|---|
| API Key / Base URL / Model | 评论分析、自适应图表等 AI 功能（兼容 OpenAI 接口：DeepSeek、Qwen 等） |
| Vision 配置 | 市场规划「字段提取」的图片识别通道（留空用主配置） |
| 主程序 update.json | 公司共享盘路径、`file://` 或公开 HTTPS 地址 |
| GitHub 仓库 | 高级插件更新通道，仅下载插件 ZIP，不替换主程序 |

> 从 V1.9.1 起，用户配置保存在 `%LOCALAPPDATA%\PM Stack\config.json`；API Key
> 使用 Windows DPAPI 加密。EXE 同目录的旧配置会自动迁移并清除明文密钥。

## 主程序自动更新（V1.10.0）

首次分发时，把以下三个文件放在同一文件夹交给同事：

```text
PM Stack.exe
PM Stack Updater.exe
update-channel.json
```

更新源可选公司共享盘或公开 GitHub Releases。客户端读取 `update.json`，下载
`PM Stack.exe` 到本机临时目录，校验文件大小和 SHA-256 后启动独立更新器；独立更新器
等待主程序退出，保留 `PM Stack.previous.exe`，替换成功后重新启动。详细发布流程见
`发布更新指南.md`。

---

### 辅助脚本（无独立界面，被上述功能调用或备用）

- `scripts/trend_chart.py` — 通用趋势图绘制
- `scripts/figure_display.py` — 图表展示工具
- `scripts/review_visual_dashboard_ai.py` — 评论可视化看板（实验性）
- `scripts/comments_step_1&2.py` — 评论分析两步合并版（备用）
