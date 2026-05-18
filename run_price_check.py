"""
GitHub Actions 价格检测入口
从环境变量 PROJECTS_JSON 读取配置，检测一轮价格后退出
"""
import json
import logging
import os
import sys
import types
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ── 从环境变量 或 本地文件加载配置 ──────────────────────────────
raw = os.environ.get("PROJECTS_JSON", "")
if not raw:
    # 本地运行时：从同目录下的 projects.json 读取
    local_cfg = Path(__file__).parent / "projects.json"
    if local_cfg.exists():
        raw = local_cfg.read_text(encoding="utf-8")
        print(f"📂 从本地文件加载配置：{local_cfg}")
    else:
        print("❌ 未找到 PROJECTS_JSON 环境变量或 projects.json 文件")
        sys.exit(1)

try:
    projects_data = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"❌ PROJECTS_JSON 格式错误: {e}")
    sys.exit(1)

# ── 构建 config 模块 ──────────────────────────────────────────
cfg = types.ModuleType("config")
cfg.PROJECTS               = projects_data["projects"]
cfg.DAILY_REPORT_WEBHOOKS  = [p["webhook"] for p in cfg.PROJECTS]
cfg.REGIONS = [
    {"name": "北京", "jd_search": "https://search.jd.com/Search?keyword=%E5%8C%97%E4%BA%AC+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "上海", "jd_search": "https://search.jd.com/Search?keyword=%E4%B8%8A%E6%B5%B7+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "广东", "jd_search": "https://search.jd.com/Search?keyword=%E5%B9%BF%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "浙江", "jd_search": "https://search.jd.com/Search?keyword=%E6%B5%99%E6%B1%9F+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "江苏", "jd_search": "https://search.jd.com/Search?keyword=%E6%B1%9F%E8%8B%8F+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "四川", "jd_search": "https://search.jd.com/Search?keyword=%E5%9B%9B%E5%B7%9D+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "湖北", "jd_search": "https://search.jd.com/Search?keyword=%E6%B9%96%E5%8C%97+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
    {"name": "山东", "jd_search": "https://search.jd.com/Search?keyword=%E5%B1%B1%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8"},
]
cfg.SUBSIDY_KEYWORDS = ["以旧换新", "家电补贴", "国家补贴", "惠民补贴", "消费补贴", "家电下乡", "国补", "京东补贴"]
cfg.PRICE_INTERVAL_MIN     = 5
cfg.DAILY_REPORT_HOUR      = 9
cfg.RETRY_TIMES            = 3
cfg.RETRY_DELAY            = 5
cfg.REQUEST_HEADERS        = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.jd.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
sys.modules["config"] = cfg

from jd_monitor import JDPriceFetcher, FeishuBot, PriceCache

jd    = JDPriceFetcher()
bot   = FeishuBot()
cache = PriceCache()

total_skus = sum(len(p['skus']) for p in cfg.PROJECTS)
print(f"监控项目: {len(cfg.PROJECTS)} 个  SKU总数: {total_skus}")

for project in cfg.PROJECTS:
    proj_name = project["name"]
    webhook   = project["webhook"]
    owner     = project["owner"]
    sku_list  = project["skus"]

    # 批量查询本项目所有 SKU（内部每 20 个一批，大幅减少 API 调用次数）
    all_skus   = [item["sku"] for item in sku_list]
    sku_to_name = {item["sku"]: item["name"] for item in sku_list}
    prices     = jd.get_prices_batch(all_skus)

    print(f"[{proj_name}] 查询 {len(all_skus)} 个 SKU，成功返回 {len(prices)} 个")

    for sku, name in sku_to_name.items():
        new_price = prices.get(sku)
        if new_price is None:
            print(f"  [跳过] {name}（{sku}）价格获取失败")
            continue

        old_price = cache.get(sku)
        cache.set(sku, new_price)

        if old_price is None:
            print(f"  [基准] {name} = {new_price:.2f} 元（首次记录）")
        elif new_price < old_price:
            print(f"  [降价] {name}: {old_price:.2f} → {new_price:.2f}")
            bot.notify_price_down(webhook, proj_name, owner, sku, name, old_price, new_price)
        elif new_price > old_price:
            print(f"  [涨价] {name}: {old_price:.2f} → {new_price:.2f}")
            bot.notify_price_up(webhook, proj_name, owner, sku, name, old_price, new_price)
        else:
            print(f"  [不变] {name} = {new_price:.2f} 元")

print("价格检测完成")
