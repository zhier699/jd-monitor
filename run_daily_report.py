"""
GitHub Actions 国补日报入口
从环境变量 PROJECTS_JSON 读取配置，抓取国补新闻后发送日报
"""
import json
import logging
import os
import sys
import types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

raw = os.environ.get("PROJECTS_JSON", "")
if not raw:
    print("❌ 未找到 PROJECTS_JSON 环境变量")
    sys.exit(1)

projects_data = json.loads(raw)

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
sys.modules["config"] = cfg

from jd_monitor import SubsidyFetcher, FeishuBot

bot     = FeishuBot()
fetcher = SubsidyFetcher()

print("正在抓取国补新闻（Google News RSS）...")
news = fetcher.fetch_news()
print(f"获取到 {len(news)} 条相关新闻")
for n in news:
    print(f"  [{n['date']}] {n['source']}: {n['title'][:50]}")

print("发送日报...")
for webhook in cfg.DAILY_REPORT_WEBHOOKS:
    bot.notify_subsidy_daily(webhook, news)

print("国补日报发送完成")
