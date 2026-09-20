"""
亚马逊评论爬虫 - 配置文件
"""

import os

from .paths import BROWSER_PROFILE_DIR, DEBUG_DIR as APP_DEBUG_DIR, EXPORT_DIR

# 亚马逊站点配置
# 可选: amazon.com, amazon.co.uk, amazon.de, amazon.co.jp, amazon.com.au
DEFAULT_MARKETPLACE = "amazon.com"

MARKETPLACES = {
    "amazon.com": "https://www.amazon.com",
    "amazon.co.uk": "https://www.amazon.co.uk",
    "amazon.de": "https://www.amazon.de",
    "amazon.co.jp": "https://www.amazon.co.jp",
    "amazon.com.au": "https://www.amazon.com.au",
}

# Playwright 直接使用 Windows 已安装的 Edge，不需要 msedgedriver.exe。
PLAYWRIGHT_BROWSER_CHANNEL = os.environ.get("REVIEWCOLLECTOR_BROWSER_CHANNEL", "msedge")
BROWSER_USER_DATA_DIR = str(BROWSER_PROFILE_DIR)

# 运行模式：debug 调试阶段更快；safe 正式爬取更慢
RUN_MODE = os.environ.get("REVIEWCOLLECTOR_RUN_MODE", "safe").lower()

if RUN_MODE == "debug":
    # 调试模式：用于验证点击、选择器和保存流程
    MIN_DELAY = 0.5
    MAX_DELAY = 1.5
    IMPLICIT_WAIT = 2
    CLICK_DELAY_MIN = 0.3
    CLICK_DELAY_MAX = 0.8
    LOAD_MORE_DELAY_MIN = 1
    LOAD_MORE_DELAY_MAX = 2
else:
    # 正式模式：更接近人工节奏，降低账号/验证风险
    MIN_DELAY = 4
    MAX_DELAY = 8
    IMPLICIT_WAIT = 5
    CLICK_DELAY_MIN = 1.5
    CLICK_DELAY_MAX = 3
    LOAD_MORE_DELAY_MIN = 2
    LOAD_MORE_DELAY_MAX = 4

# 页面加载超时时间（秒）
PAGE_LOAD_TIMEOUT = 30

# 每个星级最多爬取页数（每页约 10 条评论）
MAX_REVIEW_PAGES = 10

# 每个星级最多评论数
MAX_REVIEWS_PER_STAR = 100

# 默认星级顺序
STAR_LEVELS = [5, 4, 3, 2, 1]

# Amazon 评论星级筛选参数
STAR_FILTER_MAP = {
    5: "five_star",
    4: "four_star",
    3: "three_star",
    2: "two_star",
    1: "one_star",
}

# 输出目录
OUTPUT_DIR = str(EXPORT_DIR)

# 调试输出：保存当前页面 html / 截图，用于定位“未找到评论”问题
DEBUG_SAVE_PAGE = True
DEBUG_DIR = str(APP_DEBUG_DIR)
