import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# === 1. 设置中文字体 ===
import platform
system_name = platform.system()
if system_name == "Windows":
    plt.rcParams['font.sans-serif'] = ['SimHei']
elif system_name == "Darwin":  # Mac OS
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS']
else:  # Linux
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# === 2. 准备数据 ===
labels = ['TESSAN', 'Anker', 'LENCENT', 'Denlane', 'JSVER', 'Bigfish',
          'vutizal', 'Towkom', 'Clomnpe', 'ANVODE', '其他']
sizes = [18, 3, 5, 6, 4, 5, 5, 1, 4, 4, 45]

colors = [
    '#5B9BD5', '#D9534F', '#A9D18E', '#A5A5A5', '#5DD3C1',
    '#F4B084', '#4A7EBB', '#6C4E3B', '#7C6C6C', '#706C94', '#408080'
]

# === 3. 设置画布 ===
plt.figure(figsize=(14, 9))

# === 4. 绘制饼图 ===
patches, texts, autotexts = plt.pie(
    sizes,
    labels=None,
    colors=colors,
    radius=0.5,             # 饼图半径缩小，为周围留出空间
    startangle=90,          # 起始角度旋转90度
    autopct='%1.0f%%',      # 显示百分比，不显示小数
    pctdistance=0.8,        # 百分比标签距离圆心的距离
    textprops={'fontsize': 30, 'weight': 'bold', 'color': 'white'} # 饼图内部文字样式
)

# === 5. 设置标题 ===
plt.title('插座适配器各品牌销量占比（DE）', fontsize=32, pad=20, weight='bold')

# === 6. 设置图例 ===
# 关键点：bbox_to_anchor 设为 (0.95, 0, 0.5, 1)，让图例紧贴饼图右侧
plt.legend(
    patches,
    labels,
    loc="center left",
    bbox_to_anchor=(0.95, 0, 0.5, 1), 
    fontsize=24,            # 图例文字超大号
    title_fontsize=24,
    frameon=False           # 去掉图例边框
)

# === 7. 保存与展示 ===
plt.axis('equal')
# 调整布局：右边留到 0.95，因为图例现在比较靠左，不需要留太多右边距
plt.tight_layout(rect=[0, 0, 0.95, 0.95])

output_file = os.getenv("PIE_OUTPUT_FILE", "插座销量占比_紧凑版.png")
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"饼图已保存到：{output_file}")

if os.getenv("SHOW_PLOT", "0").strip().lower() in ("1", "true", "yes", "y"):
    plt.show()
