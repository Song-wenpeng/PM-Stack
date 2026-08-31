import os
script_dir = os.path.dirname(os.path.abspath(__file__))

# 配置路径
ALL_IDS_FILE = os.getenv(
    "PROGRESS_ALL_IDS_FILE",
    os.path.join(script_dir, "all_ids.txt"),
)      # 包含所有类目 ID 的文件
DATA_FOLDER = os.getenv(
    "PROGRESS_DATA_FOLDER",
    "D:\\Google浏览器下载\\欧洲市场规划\\图片",
)      # 存放已爬取数据的文件夹
FILE_EXTENSION = os.getenv("PROGRESS_FILE_EXTENSION", ".png")  # 已爬取文件的扩展名
OUTPUT_FILE = os.getenv("PROGRESS_OUTPUT_FILE", os.path.join(os.getcwd(), "missing_ids.txt"))

# 1. 读取所有需要爬取的 ID
with open(ALL_IDS_FILE, "r", encoding="utf-8") as f:
    all_ids = {line.strip() for line in f if line.strip()}

# 2. 读取已爬取的 ID（从文件名中提取）
crawled_ids = set()
for filename in os.listdir(DATA_FOLDER):
    if filename.endswith(FILE_EXTENSION):
        id_part = filename[: -len(FILE_EXTENSION)]   # 去掉扩展名
        crawled_ids.add(id_part)

# 3. 计算缺失的 ID
missing_ids = all_ids - crawled_ids

# 4. 输出缺失 ID 列表（每行一个）
print(f"总共需要 {len(all_ids)} 个，已爬取 {len(crawled_ids)} 个，缺失 {len(missing_ids)} 个")
if missing_ids:
    print("\n缺失的类目 ID 列表：")
    for mid in sorted(missing_ids, key=lambda x: int(x) if x.isdigit() else x):
        print(mid)
else:
    print("恭喜，所有类目都已爬取！")

# （可选）保存缺失 ID 到文件
output_dir = os.path.dirname(OUTPUT_FILE)
if output_dir:
    os.makedirs(output_dir, exist_ok=True)

with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
    for mid in sorted(missing_ids):
        out.write(mid + "\n")
print(f"\n缺失 ID 已保存到 {OUTPUT_FILE}")
