# -*- coding: utf-8 -*-
"""市场机会得分：对候选类目做跨类目相对分位打分。

分析基准日不再写死：默认取运行当日，可用 MARKET_ANALYSIS_DATE 或界面显式指定。
基准日、权重、参与文件与样本量都会写入输出的「参数快照」表，便于事后追溯；
各维度分数是本次参与类目之间的相对分位，不是绝对阈值。
"""
import datetime as dt
import glob
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Direct CLI and the embedded runner both use the same safe I/O implementation.
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.report_io import (normalized_path, resolve_reference_date, same_file,
                            write_excel, SafeWriteError)

# =========================
# 配置区
# =========================
DEFAULT_DATA_DIR = r"D:\Google浏览器下载\欧洲市场规划\德国市场"
DEFAULT_OUTPUT_FILE = r"D:\Google浏览器下载\欧洲市场规划\德国市场_类目评估汇总.xlsx"

# 新品定义：最近365天上架
NEW_PRODUCT_DAYS = 365

# 一级维度权重（总分100）
WEIGHTS = {
    "市场体量": 30,
    "竞争结构": 20,
    "价格环境": 15,
    "新品成长机会": 25,
    "门槛与热度": 10
}

# 各维度下的子指标权重
SUB_WEIGHTS = {
    "市场体量": {
        "Top100月总销额": 15,
        "Top100月总销量": 10,
        "中位SKU月销额": 5
    },
    "竞争结构": {
        "CR10销额占比": 8,      # 反向
        "CR20销额占比": 6,      # 反向
        "长尾销额占比": 6       # 正向
    },
    "价格环境": {
        "中位价格": 6,
        "价格变异系数": 4,
        "核心价格带SKU占比": 5   # 反向
    },
    "新品成长机会": {
        "新品数占比": 5,
        "新品销量占比": 7,
        "新品销额占比": 7,
        "Top20新品数": 3,
        "新品爬坡效率": 3
    },
    "门槛与热度": {
        "前20平均评分数": 4,         # 反向
        "Top100月新增评分总数": 3,
        "新品月新增评分占比": 3
    }
}


# =========================
# 工具函数
# =========================
def safe_num(x):
    """清洗各种带逗号、货币符号、百分号、空值的内容"""
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if s == "":
        return np.nan
    s = s.replace(",", "")
    s = s.replace("€", "")
    s = s.replace("%", "")
    s = re.sub(r"[^\d\.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return np.nan
    try:
        return float(s)
    except:
        return np.nan


def extract_category_id(filename):
    """从文件名中提取类目ID，优先提取5位及以上连续数字"""
    stem = os.path.splitext(os.path.basename(filename))[0]
    nums = re.findall(r"\d{5,}", stem)
    if nums:
        return nums[0]
    return stem


def load_excel_file(file_path):
    """优先读取 DE sheet，没有就读第一个。

    用上下文管理器确保关闭句柄：Windows 上未关闭的 ExcelFile 会一直占用源文件，
    导致用户无法移动、删除或覆盖自己刚抓的数据。
    """
    with pd.ExcelFile(file_path) as xls:
        sheet_name = "DE" if "DE" in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(xls, sheet_name=sheet_name)
    df.columns = df.columns.astype(str).str.strip()
    return df, sheet_name


def find_col(df, candidates, required=True):
    """按候选列名查找真实列"""
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    if required:
        raise ValueError(f"未找到列，候选列名：{candidates}")
    return None


def quantile_score(series, reverse=False):
    """
    按候选类目横向分位数打 1-5 分
    前20%=5分，后20%=1分
    reverse=True 表示值越大越差
    """
    s = pd.to_numeric(series, errors="coerce")
    ranks = s.rank(method="average", pct=True)

    if reverse:
        ranks = 1 - ranks

    scores = pd.Series(index=s.index, dtype=float)
    scores[(ranks <= 0.20)] = 1
    scores[(ranks > 0.20) & (ranks <= 0.40)] = 2
    scores[(ranks > 0.40) & (ranks <= 0.60)] = 3
    scores[(ranks > 0.60) & (ranks <= 0.80)] = 4
    scores[(ranks > 0.80)] = 5

    return scores.fillna(1)


def score_median_price(x):
    """
    中位价格：只做低价惩罚，不惩罚高价类目
    跨类目比较时，高价不一定坏，但过低价通常意味着利润空间差
    """
    if pd.isna(x):
        return 1
    if x < 6:
        return 1
    elif x < 10:
        return 2
    elif x < 15:
        return 3
    elif x < 20:
        return 4
    else:
        return 5


def score_price_cv(x):
    """
    价格变异系数打分：
    太低 -> 高度同质化
    太高 -> 类目混杂
    中间更合理
    """
    if pd.isna(x):
        return 1
    if 0.15 <= x <= 0.60:
        return 5
    elif 0.10 <= x < 0.15 or 0.60 < x <= 0.80:
        return 4
    elif 0.05 <= x < 0.10 or 0.80 < x <= 1.00:
        return 3
    elif 0.02 <= x < 0.05 or 1.00 < x <= 1.20:
        return 2
    else:
        return 1


def months_since_launch(launch_date, analysis_date):
    if pd.isna(launch_date):
        return np.nan
    days = (analysis_date - launch_date).days
    return max(days / 30.0, 1)


def resolve_analysis_date(raw='', today=None):
    """返回 (分析基准日 Timestamp, 来源说明)。

    默认取运行当日，因为「上架天数」「是否新品」必须相对一个明确的时点计算；
    写死一个过期日期会让该日之后上架的商品得到负天数并被漏判为非新品。
    格式解析与界面共用 core.report_io.resolve_reference_date，避免两处口径不一致。
    """
    stamp, source = resolve_reference_date(raw, today=today, label='分析基准日',
                                           env_name='MARKET_ANALYSIS_DATE')
    return pd.Timestamp(stamp), source


def collect_files(data_dir, output):
    """只有确认是旧评分报告才排除同源输出，不能把真实输入排除后覆盖。"""
    candidates = [f for f in glob.glob(os.path.join(str(data_dir), '*.xlsx'))
                  if not os.path.basename(f).startswith('~$')]
    kept, excluded = [], []
    for path in candidates:
        if not same_file(path, output):
            kept.append(path)
            continue
        try:
            with pd.ExcelFile(path) as book:
                names = set(book.sheet_names)
                report_sheets = {'类目汇总评分', '原始Top100汇总', '评分说明'}
                is_report = (report_sheets <= names <= report_sheets | {'参数快照'}
                             and {'类目ID', '市场机会总分', '类目标签'} <= set(
                                 pd.read_excel(book, sheet_name='类目汇总评分', nrows=0).columns)
                             and {'来源文件', '类目ID'} <= set(
                                 pd.read_excel(book, sheet_name='原始Top100汇总', nrows=0).columns))
        except Exception:
            is_report = False
        if not is_report:
            raise ValueError(f'禁止覆盖输入原件：输出与候选类目文件相同：{path}。请选择其他输出文件。')
        excluded.append(path)
    return sorted(kept), excluded


def build_relative_price_bands(df, price_col="价格_num"):
    """
    基于类目中位价建立相对价格带
    - <0.7x 中位价：低价带
    - 0.7~0.9x：次低价带
    - 0.9~1.1x：核心价带
    - 1.1~1.4x：次高价带
    - >1.4x：高价带
    """
    median_price = df[price_col].median(skipna=True)

    if pd.isna(median_price) or median_price <= 0:
        df["相对价格带"] = np.nan
        return df, np.nan, np.nan, np.nan

    conditions = [
        df[price_col] < 0.7 * median_price,
        (df[price_col] >= 0.7 * median_price) & (df[price_col] < 0.9 * median_price),
        (df[price_col] >= 0.9 * median_price) & (df[price_col] <= 1.1 * median_price),
        (df[price_col] > 1.1 * median_price) & (df[price_col] <= 1.4 * median_price),
        df[price_col] > 1.4 * median_price
    ]
    labels = ["低价带", "次低价带", "核心价带", "次高价带", "高价带"]

    df["相对价格带"] = np.select(conditions, labels, default="未知")

    band_share = df["相对价格带"].value_counts(normalize=True, dropna=False)
    dominant_band = band_share.idxmax() if len(band_share) > 0 else np.nan
    dominant_band_share = band_share.max() if len(band_share) > 0 else np.nan

    core_band_share = (
        ((df[price_col] >= 0.9 * median_price) & (df[price_col] <= 1.1 * median_price)).mean()
        if len(df) > 0 else np.nan
    )

    return df, dominant_band, dominant_band_share, core_band_share


# =========================
# 单个类目文件汇总
# =========================
def summarize_category_file(file_path, analysis_date):
    df, sheet_name = load_excel_file(file_path)
    category_id = extract_category_id(file_path)

    # 列名识别
    col_subcat = find_col(df, ["小类目"], required=False)
    col_bsr = find_col(df, ["小类BSR"], required=False)
    col_units = find_col(df, ["月销量"])
    col_revenue = find_col(df, ["月销售额(€)", "月销售额"])
    col_price = find_col(df, ["价格(€)", "价格"])
    col_reviews = find_col(df, ["评分数", "评论数"])
    col_new_reviews = find_col(df, ["月新增评分数", "月新增评论数"])
    col_rating = find_col(df, ["评分"], required=False)
    col_launch = find_col(df, ["上架时间"])

    # 仅保留有效行
    if "ASIN" in df.columns:
        df = df[df["ASIN"].notna()].copy()

    # 数值清洗
    df["月销量_num"] = df[col_units].apply(safe_num)
    df["月销额_num"] = df[col_revenue].apply(safe_num)
    df["价格_num"] = df[col_price].apply(safe_num)
    df["评分数_num"] = df[col_reviews].apply(safe_num)
    df["月新增评分数_num"] = df[col_new_reviews].apply(safe_num)
    df["评分_num"] = df[col_rating].apply(safe_num) if col_rating else np.nan
    df["上架时间_dt"] = pd.to_datetime(df[col_launch], errors="coerce")

    # 排序：优先按小类BSR升序；如果没有则按月销额降序
    if col_bsr:
        df["BSR_num"] = df[col_bsr].apply(safe_num)
        df = df.sort_values(by="BSR_num", ascending=True, na_position="last").copy()
    else:
        df = df.sort_values(by="月销额_num", ascending=False, na_position="last").copy()

    # 只取Top100
    df = df.head(100).copy()
    df.reset_index(drop=True, inplace=True)

    if len(df) == 0:
        return None, None

    # 基本信息
    category_name = ""
    if col_subcat and df[col_subcat].notna().any():
        category_name = str(df[col_subcat].dropna().iloc[0]).strip()

    # =========================
    # 1. 市场体量
    # =========================
    total_units = df["月销量_num"].sum(skipna=True)
    total_revenue = df["月销额_num"].sum(skipna=True)
    median_units = df["月销量_num"].median(skipna=True)
    median_revenue = df["月销额_num"].median(skipna=True)

    # =========================
    # 2. 竞争结构
    # =========================
    top10_revenue = df.head(10)["月销额_num"].sum(skipna=True)
    top20_revenue = df.head(20)["月销额_num"].sum(skipna=True)
    tail31_100_revenue = df.iloc[30:100]["月销额_num"].sum(skipna=True)

    cr10_revenue_share = top10_revenue / total_revenue if total_revenue > 0 else np.nan
    cr20_revenue_share = top20_revenue / total_revenue if total_revenue > 0 else np.nan
    tail31_100_revenue_share = tail31_100_revenue / total_revenue if total_revenue > 0 else np.nan

    # HHI
    if total_revenue > 0:
        revenue_shares = (df["月销额_num"] / total_revenue).fillna(0)
        hhi = (revenue_shares ** 2).sum()
    else:
        hhi = np.nan

    # =========================
    # 3. 价格环境
    # =========================
    avg_price = df["价格_num"].mean(skipna=True)
    median_price = df["价格_num"].median(skipna=True)
    std_price = df["价格_num"].std(skipna=True)
    price_cv = std_price / avg_price if pd.notna(avg_price) and avg_price > 0 else np.nan

    df, dominant_rel_band, dominant_rel_band_share, core_band_share = build_relative_price_bands(df, price_col="价格_num")

    # =========================
    # 4. 新品成长机会
    # =========================
    df["上架天数"] = (analysis_date - df["上架时间_dt"]).dt.days
    df["是否新品"] = [bool(x) for x in df["上架天数"].between(0, NEW_PRODUCT_DAYS, inclusive="both")]

    # 上架时间晚于基准日说明源数据或基准日有问题；负天数不是「很旧」，必须显式暴露。
    future_launch = int((df["上架天数"] < 0).sum())
    if future_launch:
        latest = df.loc[df["上架天数"] < 0, "上架时间_dt"].max()
        print(f"  [警告] {os.path.basename(file_path)} 有 {future_launch} 行上架时间晚于分析基准日"
              f"（最晚 {latest:%Y-%m-%d}），这些行的上架天数为负、不计入新品；"
              f"请确认基准日是否早于抓数时点。")
    missing_launch = int(df["上架时间_dt"].isna().sum())
    if missing_launch:
        print(f"  [提示] {os.path.basename(file_path)} 有 {missing_launch} 行缺少可解析的上架时间，"
              f"不计入新品。")

    new_df = df[df["是否新品"]].copy()

    new_count = len(new_df)
    new_count_share = new_count / len(df) if len(df) > 0 else np.nan
    new_units_share = new_df["月销量_num"].sum(skipna=True) / total_units if total_units > 0 else np.nan
    new_revenue_share = new_df["月销额_num"].sum(skipna=True) / total_revenue if total_revenue > 0 else np.nan
    top20_new_count = df.head(20)["是否新品"].sum()

    if len(new_df) > 0:
        new_df["上架月数"] = new_df["上架时间_dt"].apply(lambda x: months_since_launch(x, analysis_date))
        new_df["单月爬坡效率"] = new_df["月销量_num"] / new_df["上架月数"]
        new_ramp_efficiency = new_df["单月爬坡效率"].mean(skipna=True)
    else:
        new_ramp_efficiency = np.nan

    # =========================
    # 5. 门槛与热度
    # =========================
    top20_avg_reviews = df.head(20)["评分数_num"].mean(skipna=True)
    top20_median_reviews = df.head(20)["评分数_num"].median(skipna=True)
    total_monthly_new_reviews = df["月新增评分数_num"].sum(skipna=True)
    new_monthly_new_reviews_share = (
        new_df["月新增评分数_num"].sum(skipna=True) / total_monthly_new_reviews
        if total_monthly_new_reviews > 0 else np.nan
    )

    # 附加信息
    avg_rating = df["评分_num"].mean(skipna=True)

    summary = {
        "类目ID": category_id,
        "类目名称": category_name,
        "文件名": os.path.basename(file_path),
        "Sheet": sheet_name,
        "样本数": len(df),
        "分析基准日": f"{analysis_date:%Y-%m-%d}",
        "上架晚于基准日数": future_launch,
        "上架时间缺失数": missing_launch,

        # 市场体量
        "Top100月总销量": total_units,
        "Top100月总销额": total_revenue,
        "中位SKU月销量": median_units,
        "中位SKU月销额": median_revenue,

        # 竞争结构
        "CR10销额占比": cr10_revenue_share,
        "CR20销额占比": cr20_revenue_share,
        "长尾销额占比": tail31_100_revenue_share,
        "HHI": hhi,

        # 价格环境
        "平均价格": avg_price,
        "中位价格": median_price,
        "价格标准差": std_price,
        "价格变异系数": price_cv,
        "主相对价格带": dominant_rel_band,
        "主相对价格带SKU占比": dominant_rel_band_share,
        "核心价格带SKU占比": core_band_share,

        # 新品成长
        "近一年新品数": new_count,
        "新品数占比": new_count_share,
        "新品销量占比": new_units_share,
        "新品销额占比": new_revenue_share,
        "Top20新品数": top20_new_count,
        "新品爬坡效率": new_ramp_efficiency,

        # 门槛与热度
        "前20平均评分数": top20_avg_reviews,
        "前20中位评分数": top20_median_reviews,
        "Top100月新增评分总数": total_monthly_new_reviews,
        "新品月新增评分占比": new_monthly_new_reviews_share,

        # 附加
        "平均评分": avg_rating
    }

    return summary, df


# =========================
# 打分
# =========================
def apply_scores(summary_df):
    """按固定权重折算到100分制；公式与权重与历史版本一致。"""
    # 1. 市场体量
    summary_df["score_总销额"] = quantile_score(summary_df["Top100月总销额"])
    summary_df["score_总销量"] = quantile_score(summary_df["Top100月总销量"])
    summary_df["score_中位销额"] = quantile_score(summary_df["中位SKU月销额"])

    summary_df["市场体量分"] = (
        summary_df["score_总销额"] * SUB_WEIGHTS["市场体量"]["Top100月总销额"] +
        summary_df["score_总销量"] * SUB_WEIGHTS["市场体量"]["Top100月总销量"] +
        summary_df["score_中位销额"] * SUB_WEIGHTS["市场体量"]["中位SKU月销额"]
    ) / (5 * sum(SUB_WEIGHTS["市场体量"].values())) * WEIGHTS["市场体量"]

    # 2. 竞争结构
    summary_df["score_CR10"] = quantile_score(summary_df["CR10销额占比"], reverse=True)
    summary_df["score_CR20"] = quantile_score(summary_df["CR20销额占比"], reverse=True)
    summary_df["score_长尾"] = quantile_score(summary_df["长尾销额占比"])

    summary_df["竞争结构分"] = (
        summary_df["score_CR10"] * SUB_WEIGHTS["竞争结构"]["CR10销额占比"] +
        summary_df["score_CR20"] * SUB_WEIGHTS["竞争结构"]["CR20销额占比"] +
        summary_df["score_长尾"] * SUB_WEIGHTS["竞争结构"]["长尾销额占比"]
    ) / (5 * sum(SUB_WEIGHTS["竞争结构"].values())) * WEIGHTS["竞争结构"]

    # 3. 价格环境
    summary_df["score_中位价格"] = summary_df["中位价格"].apply(score_median_price)
    summary_df["score_价格CV"] = summary_df["价格变异系数"].apply(score_price_cv)
    summary_df["score_核心价格带集中"] = quantile_score(summary_df["核心价格带SKU占比"], reverse=True)

    summary_df["价格环境分"] = (
        summary_df["score_中位价格"] * SUB_WEIGHTS["价格环境"]["中位价格"] +
        summary_df["score_价格CV"] * SUB_WEIGHTS["价格环境"]["价格变异系数"] +
        summary_df["score_核心价格带集中"] * SUB_WEIGHTS["价格环境"]["核心价格带SKU占比"]
    ) / (5 * sum(SUB_WEIGHTS["价格环境"].values())) * WEIGHTS["价格环境"]

    # 4. 新品成长机会
    summary_df["score_新品数占比"] = quantile_score(summary_df["新品数占比"])
    summary_df["score_新品销量占比"] = quantile_score(summary_df["新品销量占比"])
    summary_df["score_新品销额占比"] = quantile_score(summary_df["新品销额占比"])
    summary_df["score_Top20新品数"] = quantile_score(summary_df["Top20新品数"])
    summary_df["score_新品爬坡效率"] = quantile_score(summary_df["新品爬坡效率"])

    summary_df["新品成长机会分"] = (
        summary_df["score_新品数占比"] * SUB_WEIGHTS["新品成长机会"]["新品数占比"] +
        summary_df["score_新品销量占比"] * SUB_WEIGHTS["新品成长机会"]["新品销量占比"] +
        summary_df["score_新品销额占比"] * SUB_WEIGHTS["新品成长机会"]["新品销额占比"] +
        summary_df["score_Top20新品数"] * SUB_WEIGHTS["新品成长机会"]["Top20新品数"] +
        summary_df["score_新品爬坡效率"] * SUB_WEIGHTS["新品成长机会"]["新品爬坡效率"]
    ) / (5 * sum(SUB_WEIGHTS["新品成长机会"].values())) * WEIGHTS["新品成长机会"]

    # 5. 门槛与热度
    summary_df["score_前20评论数"] = quantile_score(summary_df["前20平均评分数"], reverse=True)
    summary_df["score_月新增评论总数"] = quantile_score(summary_df["Top100月新增评分总数"])
    summary_df["score_新品新增评论占比"] = quantile_score(summary_df["新品月新增评分占比"])

    summary_df["门槛与热度分"] = (
        summary_df["score_前20评论数"] * SUB_WEIGHTS["门槛与热度"]["前20平均评分数"] +
        summary_df["score_月新增评论总数"] * SUB_WEIGHTS["门槛与热度"]["Top100月新增评分总数"] +
        summary_df["score_新品新增评论占比"] * SUB_WEIGHTS["门槛与热度"]["新品月新增评分占比"]
    ) / (5 * sum(SUB_WEIGHTS["门槛与热度"].values())) * WEIGHTS["门槛与热度"]

    # 总分
    summary_df["市场机会总分"] = (
        summary_df["市场体量分"] +
        summary_df["竞争结构分"] +
        summary_df["价格环境分"] +
        summary_df["新品成长机会分"] +
        summary_df["门槛与热度分"]
    )

    summary_df["类目标签"] = summary_df["市场机会总分"].apply(classify_tag)
    summary_df["建议动作"] = summary_df.apply(make_recommendation, axis=1)

    # 排序
    return summary_df.sort_values(by="市场机会总分", ascending=False).reset_index(drop=True)


# =========================
# 标签与建议
# =========================
def classify_tag(x):
    if pd.isna(x):
        return "D"
    if x >= 80:
        return "A"
    elif x >= 65:
        return "B"
    elif x >= 50:
        return "C"
    else:
        return "D"


def make_recommendation(row):
    score = row["市场机会总分"]
    if pd.isna(score):
        return "数据不足"
    if score >= 80:
        return "优先深挖"
    elif score >= 65:
        return "重点观察"
    elif score >= 50:
        return "谨慎评估"
    else:
        return "暂不优先"


def build_score_guide():
    return pd.DataFrame([
        ["市场体量", "看类目规模是否足够大", "Top100月总销额、Top100月总销量、中位SKU月销额"],
        ["竞争结构", "看头部是否垄断，长尾是否有空间", "CR10销额占比、CR20销额占比、长尾销额占比"],
        ["价格环境", "看价格是否低到不值得做，以及类目内部是否过于拥挤", "中位价格（低价惩罚）、价格变异系数、核心价格带SKU占比"],
        ["新品成长机会", "看近一年新品是否还有起量机会", "新品数占比、新品销量占比、新品销额占比、Top20新品数、新品爬坡效率"],
        ["门槛与热度", "看进入门槛和当前活跃度", "前20平均评分数、Top100月新增评分总数、新品月新增评分占比"],
        ["打分口径", "各维度得分是本次参与类目之间的相对分位，不是绝对阈值",
         "前20%记5分、后20%记1分；参与文件集合变化时，同一类目的分数与标签可能随之变化"],
        ["基准日", "上架天数与新品判定相对「分析基准日」计算",
         "默认取运行当日，可在界面或 MARKET_ANALYSIS_DATE 指定；实际取值见「参数快照」表"],
    ], columns=["一级维度", "解释", "核心指标"])


def build_snapshot(analysis_date, date_source, files, summary_df, raw_row_count):
    rows = [
        ("分析基准日", f"{analysis_date:%Y-%m-%d}"),
        ("基准日来源", date_source),
        ("新品天数阈值", str(NEW_PRODUCT_DAYS)),
        ("参与类目文件数", str(len(files))),
        ("参与文件", "；".join(os.path.basename(f) for f in files)),
        ("成功汇总类目数", str(len(summary_df))),
        ("原始Top100行数", str(raw_row_count)),
        ("总分构成", "；".join(f"{name}{weight}分" for name, weight in WEIGHTS.items())),
        ("打分方式", "各维度按参与类目相对分位打1-5分，加权后折算到100分制"),
        ("生成时间", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    return pd.DataFrame({"参数": [item[0] for item in rows], "值": [item[1] for item in rows]})


# =========================
# 主入口
# =========================
def main():
    data_dir = os.getenv("MARKET_DATA_DIR", DEFAULT_DATA_DIR)
    try:
        output = normalized_path(os.getenv("MARKET_OUTPUT_FILE", DEFAULT_OUTPUT_FILE))
        if output.suffix.lower() != '.xlsx':
            raise ValueError('输出必须为 .xlsx 文件。')
        analysis_date, date_source = resolve_analysis_date(os.getenv("MARKET_ANALYSIS_DATE", ""))
    except ValueError as exc:
        print(f"机会得分未完成：{exc}")
        return 1

    print("=" * 60)
    print("  市场机会得分")
    print("=" * 60)
    print(f"  数据目录:   {data_dir}")
    print(f"  输出文件:   {output}")
    print(f"  分析基准日: {analysis_date:%Y-%m-%d}（{date_source}）")

    try:
        files, excluded = collect_files(data_dir, output)
    except ValueError as exc:
        print(f"机会得分未完成：{exc}")
        return 1
    for path in excluded:
        print(f"  已排除输出文件本身，避免把上一次结果当作类目数据读入：{path}")
    if not files:
        print(f"机会得分未完成：文件夹中未找到可用作输入的 xlsx 文件：{data_dir}")
        return 1
    print(f"  候选文件:   {len(files)} 个")

    summaries = []
    raw_rows = []
    for file_path in files:
        try:
            summary, raw_df = summarize_category_file(file_path, analysis_date)
        except Exception as e:
            print(f"处理失败：{os.path.basename(file_path)} -> {e}")
            continue
        if summary is None:
            continue
        summaries.append(summary)
        temp = raw_df.copy()
        temp["来源文件"] = os.path.basename(file_path)
        temp["类目ID"] = summary["类目ID"]
        temp["类目名称"] = summary["类目名称"]
        raw_rows.append(temp)

    summary_df = pd.DataFrame(summaries)
    if len(summary_df) == 0:
        print("机会得分未完成：没有成功汇总出任何类目数据，请检查文件格式。")
        return 1

    summary_df = apply_scores(summary_df)

    raw_all_df = pd.concat(raw_rows, ignore_index=True) if raw_rows else None
    sheets = {"类目汇总评分": summary_df}
    if raw_all_df is not None:
        sheets["原始Top100汇总"] = raw_all_df
    sheets["评分说明"] = build_score_guide()
    sheets["参数快照"] = build_snapshot(analysis_date, date_source, files, summary_df,
                                       0 if raw_all_df is None else len(raw_all_df))

    try:
        # 输入目录中的类目文件全部列为保护路径，输出永不覆盖它们。
        write_excel(output, sheets, protected_paths=tuple(files))
    except SafeWriteError as exc:
        print(f"机会得分未完成：{exc}")
        return 1

    print(f"\n处理完成，结果已输出到：{output}")
    print(f"分析基准日 {analysis_date:%Y-%m-%d}；参与类目文件 {len(files)} 个；"
          f"成功汇总 {len(summary_df)} 个类目。分数为这批类目之间的相对分位，"
          f"参数与文件清单见「参数快照」表。")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
