# 展示看板 ASIN 全局筛选

## 接手信息

- 状态：已完成
- 更新日期与时区：2026-10-27（Asia/Shanghai）
- 负责人 / 集成人：本次 ASIN 筛选 Codex 会话；只读评审子智能体 asin_diagnosis
- 用户目标及验收条件：在“添加属性筛选”中提供 ASIN，支持搜索、多选，筛选同步作用于看板指标、图表、商品明细、导出和矩阵发送；验证重置、配置恢复和数据源重新加载。
- 工作目录（绝对路径）：D:\PM Stack\PM Stack
- 分支 / 起点 HEAD / 当前 HEAD：main / 7245d83cdc672636dcf344ee33319cf29a518957 / 同起点
- 本次负责的文件或模块：展示看板筛选入口、相关回归、自检、使用说明、任务索引与本记录。
- 公共文件协调 / 依赖任务：保留开工已有 16 项暂存协作检查变更、CURRENT.md/update.json 未暂存发布变更及发布记录。子智能体只读评审；研究工作树不变。
- 交付方式：主项目源码及默认 dist/PM Stack.exe 本地交付；不发布远端更新。

## 当前现场

- 已完成：新增筛选候选 filter_fields，将 ASIN 接入添加、常驻控件、重新加载和方案恢复；排名维度继续使用原 dimensions。复用底层全局查询，指标、趋势、排名、月度份额、明细、导出和矩阵发送使用同一 ASIN 范围。
- 已完成：重加载时每字段只构造一次可用值集合，避免每个选中 ASIN 重复遍历整张历史表；增加 4 项端到端回归和打包自检断言，更新使用说明。
- 已完成：48 项相关回归通过；源码自检、候选 EXE 启动自检和看板自检通过；确认候选 EXE 内嵌的本任务两份应用源码与工作树逐字节相同。
- 已完成：将验证后的候选替换默认 dist/PM Stack.exe，并更新 dist/展示看板使用说明.md。交付 EXE 大小 133782806，SHA-256 为 2341b547e50034b6c0ce6e2c3071f53799a7b947f924bac74679e799570f75bd。
- 未完成 / 已知问题：本次功能与本地 EXE 交付已完成；真实用户工作簿的人工验收未执行。重新加载后若全部选中 ASIN 已被移除，遵循既有属性规则退回不限，并在底部提示失效筛选。
- 未提交修改与未跟踪文件：本任务的 4 份源码/测试/说明文件、CURRENT.md 和本记录未暂存；既有 16 项暂存及发布任务的其他修改保留。未提交或推送。
- 已提交但未共享的内容：本任务无提交。
- 恢复位置：本工作树；交付前 EXE 与说明备份在 .runtime-local/asin-filter-20261027/before-delivery/。候选、自检报告和图片位于同任务目录，公开 v1.11.5 归档保持原状。

## 决策及原因

- 2026-10-27：复用现有属性下拉的搜索、多选及“全部 / 不限”操作，ASIN 作为市场范围条件，和其他属性取交集；明细文字搜索继续只影响明细。
- 2026-10-27：单独维护筛选候选，不把 ASIN 加入排名维度，避免为本次筛选需求额外改变分组入口。只读子智能体完成两轮评审，无阻断问题。
- 2026-10-27：使用现有 v1.11.5 spec 生成本地修复包，内部版本仍为 v1.11.5；本轮没有发布远端，不改公开更新清单、release/current 或历史归档。

## 验证证据

- 执行日期 / 工作目录 / 分支与 HEAD：2026-10-27 / D:\PM Stack\PM Stack / main / 7245d83cdc672636dcf344ee33319cf29a518957。
- 未提交被测代码：基线时应用源码与 HEAD 一致。最终 SHA-256：modules/display_dashboard.py = e636f0beedea54b6a2b06590dbafcbfcc941b4cf016cf2b590f259c04748ae93；tests/test_dashboard.py = cdf391fd2f6441b408a9946e7e43b1917a74ee4dc8186a652d4d7ce8efc9c8bb；core/dashboard_smoke.py = 0b08c166ba857f34931e0a59578199712e43a9ddaf2bea8c215546018d4829f0；docs/展示看板使用说明.md = 3d4d95ce328e55b6de7cbd1db689d4ec9354e33de93b46229281ea51a32b0997。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_dashboard tests.test_dashboard_import --timeout 240
- 解释器及必要环境：.venv-review，Python 3.12.14；tools/run_tests.py 隔离用户路径，Qt offscreen。打包按既有构建脚本规则过滤 PATH 中无关的 Poppler/libheif/jxrlib，未重新安装依赖；EXE 自检隔离 LOCALAPPDATA/USERPROFILE/TEMP/TMP，关闭自动更新。
- 结果：开工基线 33 项通过，日志 .runtime-local/test-logs/tests-20261027-135510-130886.log。
- 命令：.venv-review/Scripts/python.exe tools/run_tests.py tests.test_dashboard tests.test_dashboard_import tests.test_dashboard_chart tests.test_matrix_workspace --timeout 240
- 结果：最终 48 项全部通过，日志 .runtime-local/test-logs/tests-20261027-135756-383267.log。覆盖父ASIN/ASIN入口区分、搜索、精确勾选、多选交集、品牌分母、同比/上期比、重置移除、配置/方案、部分及全部选值失效、导出和矩阵。
- 命令：.venv-review/Scripts/python.exe -c "from tests import support; from core.config_manager import ConfigManager; ConfigManager().update({'auto_check_app_update': False, 'auto_check_update': False}); import sys; sys.argv = ['main.py', '--dashboard-check', r'D:\PM Stack\PM Stack\.runtime-local\asin-filter-20261027\source-smoke\dashboard.json']; import main; main.main()"
- 结果：源码 576 行模拟数据看板自检通过；报告和明暗主题/ASIN 搜索面板截图在 .runtime-local/asin-filter-20261027/source-smoke/。已查看新增 ASIN 筛选及搜索面板图片；筛选区正确显示两个所选 ASIN，明细 16 行与月份范围一致。
- 命令：.venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/asin-filter-20261027/candidate --workpath build/asin-filter-20261027 "PM Stack v1.11.5.spec"
- 结果：构建成功，日志 .runtime-local/asin-filter-20261027/build.log。
- 命令：.venv-review/Scripts/python.exe .runtime-local/asin-filter-20261027/verify_package.py
- 结果：候选内嵌源码字节一致；真实 EXE --startup-check 与 --dashboard-check 成功退出，报告在 .runtime-local/asin-filter-20261027/package-smoke/startup.json、dashboard.json；package-evidence.json 记录源码、EXE 指纹及自检报告。ASIN 单/多选数据、趋势、排名、矩阵断言通过。交付到 dist 后再次计算 SHA，与已验证候选完全相同。
- 原因：本轮本地功能交付，使用合成数据和隔离环境验证，不读取正式用户配置或工作簿。
- 已有失败 / 本次新增失败 / 验证局限：本轮无失败；未发布远端、未做真实用户数据的人工 GUI 验收。

## 接手后的第一步

1. 无功能待办；重启 dist/PM Stack.exe，在“添加属性筛选”搜索 ASIN，添加后搜索并多选商品。验收依据为 48 项回归、源码和 EXE 自检及交付哈希；如后续提交，只纳入本任务文件，保留既有暂存区边界。

## 变更文件

- `modules/display_dashboard.py`
- `tests/test_dashboard.py`
- `core/dashboard_smoke.py`
- `docs/展示看板使用说明.md`
- `CURRENT.md`
- `handoffs/2026-10-27-dashboard-asin-filter.md`

## 收工检查

- 开工 status 已运行；既有暂存区保持不变。收工 check 与最终变更范围核对见本次执行输出；本轮不提交，所以没有将本任务文件暂存或用他人的暂存记录作为提交证据。
