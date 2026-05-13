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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ── 从环境变量加载配置 ────────────────────────────────────────
raw = os.environ.get("PROJECTS_JSON", "")
if not raw:
    print("❌ 未找到 PROJECTS_JSON 环境变量，请在 GitHub Secrets 中配置")
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
cfg.REGIONS                = projects_data.get("regions", [])
cfg.SUBSIDY_KEYWORDS       = ["以旧换新","家电补贴","国家补贴","惠民补贴","新能源补贴","消费补贴","家电下乡","国补"]
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

print(f"监控项目: {len(cfg.PROJECTS)} 个  SKU总数: {sum(len(p['skus']) for p in cfg.PROJECTS)}")

for project in cfg.PROJECTS:
    for item in project["skus"]:
        sku, name = item["sku"], item["name"]
        new_price = jd.get_price(sku)
        if new_price is None:
            print(f"[跳过] {name}（{sku}）价格获取失败")
            continue

        old_price = cache.get(sku)
        cache.set(sku, new_price)

        if old_price is None:
            print(f"[基准] {name} = {new_price:.2f} 元（首次记录）")
        elif new_price < old_price:
            print(f"[降价] {name}: {old_price:.2f} → {new_price:.2f}")
            bot.notify_price_down(project["webhook"], project["name"],
                                  project["owner"], sku, name, old_price, new_price)
        elif new_price > old_price:
            print(f"[涨价] {name}: {old_price:.2f} → {new_price:.2f}")
            bot.notify_price_up(project["webhook"], project["name"],
                                project["owner"], sku, name, old_price, new_price)
        else:
            print(f"[不变] {name} = {new_price:.2f} 元")

print("价格检测完成")
