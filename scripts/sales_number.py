import sys
import re
import pandas as pd
import numpy as np

# ------------------ 1. 数据读取 ------------------
BASE_REQUIRED = ['ASIN', '父ASIN', '月销量', '子体销量']
# 含货币符号的列，运行时自动匹配实际列名
AMOUNT_PATTERNS = {
    '月销售额': re.compile(r'^月销售额\(.\)$'),
    '子体销售额': re.compile(r'^子体销售额\(.\)$'),
}

if len(sys.argv) >= 2:
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) >= 3 else input_file.replace('.xlsx', '_拆分结果.xlsx')
else:
    input_file = r'C:/Users/QJH/WPSDrive/311520967/WPS云盘/联动排插_US/联动排插_数据.xlsx'
    output_file = r'C:/Users/QJH/WPSDrive/311520967/WPS云盘/联动排插_US/联动排插_数据_销量拆分.xlsx'

try:
    df = pd.read_excel(input_file)

    # 动态匹配含货币符号的列名（兼容 € / $ / £ / ¥ 等）
    col_rename = {}
    for std_name, pattern in AMOUNT_PATTERNS.items():
        matches = [c for c in df.columns if pattern.match(c)]
        if matches:
            col_rename[matches[0]] = std_name

    if len(col_rename) != len(AMOUNT_PATTERNS):
        raise ValueError(
            f"数据源缺少销售额列，需要包含：月销售额(货币符号)、子体销售额(货币符号)。"
            f"\n实际列名: {list(df.columns)}"
        )

    required_cols = BASE_REQUIRED + list(col_rename.keys())

    # 校验必需列是否存在
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"数据源缺少以下列: {missing}")

    # 只提取需要的列，忽略多余列
    df = df[required_cols]

    # 列名标准化（如 '月销售额(€)' → '月销售额'）
    df = df.rename(columns=col_rename)

    print(f"原始数据行数: {len(df)}")
    print("前几行数据预览：")
    print(df.head())

    # ------------------ 2. 数据清洗 ------------------
    def clean_numeric(series):
        """
        清洗数值列：去掉逗号、货币符号（€ $ £ ¥ 元），转成数值。
        """
        return pd.to_numeric(
            series.astype(str)
                  .str.replace(',', '', regex=False)
                  .str.replace(r'[€$£¥元]', '', regex=True)
                  .str.strip()
                  .replace({'nan': np.nan, 'None': np.nan, '': np.nan}),
            errors='coerce'
        )

    # 保留原始父体数据，用于判断“是否缺失”
    df['月销量_原始'] = df['月销量']
    df['月销售额_原始'] = df['月销售额']

    # 转数值
    df['月销量'] = clean_numeric(df['月销量'])
    df['月销售额'] = clean_numeric(df['月销售额'])
    df['子体销量'] = clean_numeric(df['子体销量']).fillna(0)
    df['子体销售额'] = clean_numeric(df['子体销售额']).fillna(0)

    # ------------------ 3. 统一父体标准值 ------------------
    # 取子体销量最大的行对应的父体月销量/月销售额作为标准
    idx = df.groupby('父ASIN')['子体销量'].idxmax()
    standards = df.loc[idx, ['父ASIN', '月销量', '月销售额']].copy()
    standards.columns = ['父ASIN', '标准父体销量', '标准父体销售额']
    df = df.merge(standards, on='父ASIN', how='left')

    print("已处理父体差异：同一父体下取最大值作为标准值。")

    # ------------------ 4. 通用分配函数 ------------------
    def allocate_metric(group, parent_original_col, standard_parent_col, child_col,
                        new_col, note_col, is_integer=True):
        """
        通用分配逻辑：
        1）整组父体数据缺失 -> 保留子体原值
        2）父体值 = 0 -> 保留子体原值
        3）子体合计 > 父体值 -> 父体值疑似错误，保留子体原值
        4）父体值 > 0 且子体合计 = 0 -> 平均分配
        5）父体值 > 0 且子体合计 > 0 -> 按占比重分配
        """
        target_total = group[standard_parent_col].iloc[0]
        original_child_total = group[child_col].sum()

        no_parent_data = group[parent_original_col].isna().all()

        # 小工具：按指标类型控制保留精度
        def format_values(s):
            if is_integer:
                return s.round().astype(int)
            else:
                return s.round(2)

        # 情况1：整组没有父体数据
        if no_parent_data:
            group[new_col] = format_values(group[child_col])
            group[note_col] = '无父体数据，保留原子体值'
            return group

        # 情况2：父体数据存在，但标准父体值 = 0
        if pd.notna(target_total) and target_total == 0:
            group[new_col] = format_values(group[child_col])
            group[note_col] = '父体值为0，保留原子体值'
            return group

        # 情况3：父体值异常缺失（兜底）
        if pd.isna(target_total):
            group[new_col] = format_values(group[child_col])
            group[note_col] = '父体值异常缺失，保留原子体值'
            return group

        # 情况4：子体合计超过父体值 → 父体值疑似错误，保留原子体值
        #   （子体值均为非负，任一子体>父体 等价于 合计>父体，一个判断即可）
        if original_child_total > target_total:
            group[new_col] = format_values(group[child_col])
            group[note_col] = '子体合计超过父体，父体值疑似错误，保留原子体值'
            return group

        # 情况5：父体值 > 0，但子体合计 = 0
        if original_child_total == 0:
            equal_share = target_total / len(group)
            if is_integer:
                group[new_col] = np.round(equal_share).astype(int)
            else:
                group[new_col] = round(equal_share, 2)
            group[note_col] = '父体有值，子体合计为0，平均分配'
        else:
            # 情况6：正常按占比分配
            group['_ratio_temp'] = group[child_col] / original_child_total
            raw_alloc = group['_ratio_temp'] * target_total

            if is_integer:
                group[new_col] = raw_alloc.round().astype(int)
            else:
                group[new_col] = raw_alloc.round(2)

            group[note_col] = '按原子体占比重分配'

        # ------------------ 误差修正 ------------------
        current_sum = group[new_col].sum()

        if is_integer:
            diff = int(round(target_total - current_sum))
            if diff != 0:
                group.iloc[0, group.columns.get_loc(new_col)] += diff
        else:
            diff = round(float(target_total) - float(current_sum), 2)
            if diff != 0:
                group.iloc[0, group.columns.get_loc(new_col)] = round(
                    group.iloc[0, group.columns.get_loc(new_col)] + diff, 2
                )

        # 删除临时列
        if '_ratio_temp' in group.columns:
            group = group.drop(columns=['_ratio_temp'])

        return group

    # ------------------ 5. 分组处理 ------------------
    df.reset_index(drop=True, inplace=True)

    def process_group(group):
        # 先分配销量
        group = allocate_metric(
            group=group,
            parent_original_col='月销量_原始',
            standard_parent_col='标准父体销量',
            child_col='子体销量',
            new_col='新子体销量',
            note_col='销量分配说明',
            is_integer=True
        )

        # 再分配销售额
        group = allocate_metric(
            group=group,
            parent_original_col='月销售额_原始',
            standard_parent_col='标准父体销售额',
            child_col='子体销售额',
            new_col='新子体销售额',
            note_col='销售额分配说明',
            is_integer=False
        )

        return group

    result_df = (
        df.groupby('父ASIN', group_keys=False)
          .apply(process_group)
          .reset_index(drop=True)
    )

    # ------------------ 6. 输出结果 ------------------
    result_df.to_excel(output_file, index=False)

    print(f"计算完成！结果已保存至 '{output_file}'")
    print("\n结果前5行：")
    print(
        result_df[
            [
                'ASIN', '父ASIN',
                '月销量', '子体销量', '新子体销量', '销量分配说明',
                '月销售额', '子体销售额', '新子体销售额', '销售额分配说明'
            ]
        ].head()
    )

    # ------------------ 7. 简单校验 ------------------
    same_count = (result_df['ASIN'] == result_df['父ASIN']).sum()
    if same_count > 0:
        print(f"注意：有 {same_count} 行 ASIN 与 父ASIN 相同，请确认源数据结构。")
    else:
        print("[OK] ASIN 与 父ASIN 不相同，结构正常。")

    # ------------------ 8. 最终校验 ------------------
    print("\n=== 最终校验 ===")
    issues = []
    for parent, grp in result_df.groupby('父ASIN'):
        sales_diff = grp['新子体销量'].sum() - grp['标准父体销量'].iloc[0]
        revenue_diff = grp['新子体销售额'].sum() - grp['标准父体销售额'].iloc[0]
        if abs(sales_diff) > 1 or abs(revenue_diff) > 0.05:
            issues.append(f"  [!] {parent}: 销量差额={sales_diff}, 销售额差额={revenue_diff:.2f}")
    if issues:
        print("\n".join(issues))
    else:
        print("[OK] 所有父体组分配总和与标准值一致")

except FileNotFoundError:
    print(f"错误：找不到文件 '{input_file}'，请确认路径是否正确。")
except Exception as e:
    import traceback
    print(f"发生错误: {e}")
    traceback.print_exc()