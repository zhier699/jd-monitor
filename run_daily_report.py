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
cfg.REGIONS = [
    {"name": "北京",  "news_search": "https://www.baidu.com/s?wd=%E5%8C%97%E4%BA%AC+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "上海",  "news_search": "https://www.baidu.com/s?wd=%E4%B8%8A%E6%B5%B7+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "天津",  "news_search": "https://www.baidu.com/s?wd=%E5%A4%A9%E6%B4%A5+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "重庆",  "news_search": "https://www.baidu.com/s?wd=%E9%87%8D%E5%BA%86+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "广东",  "news_search": "https://www.baidu.com/s?wd=%E5%B9%BF%E4%B8%9C+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "浙江",  "news_search": "https://www.baidu.com/s?wd=%E6%B5%99%E6%B1%9F+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "江苏",  "news_search": "https://www.baidu.com/s?wd=%E6%B1%9F%E8%8B%8F+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "山东",  "news_search": "https://www.baidu.com/s?wd=%E5%B1%B1%E4%B8%9C+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "河南",  "news_search": "https://www.baidu.com/s?wd=%E6%B2%B3%E5%8D%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "河北",  "news_search": "https://www.baidu.com/s?wd=%E6%B2%B3%E5%8C%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "湖北",  "news_search": "https://www.baidu.com/s?wd=%E6%B9%96%E5%8C%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "湖南",  "news_search": "https://www.baidu.com/s?wd=%E6%B9%96%E5%8D%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "四川",  "news_search": "https://www.baidu.com/s?wd=%E5%9B%9B%E5%B7%9D+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "福建",  "news_search": "https://www.baidu.com/s?wd=%E7%A6%8F%E5%BB%BA+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "安徽",  "news_search": "https://www.baidu.com/s?wd=%E5%AE%89%E5%BE%BD+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "江西",  "news_search": "https://www.baidu.com/s?wd=%E6%B1%9F%E8%A5%BF+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "陕西",  "news_search": "https://www.baidu.com/s?wd=%E9%99%95%E8%A5%BF+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "辽宁",  "news_search": "https://www.baidu.com/s?wd=%E8%BE%BD%E5%AE%81+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "吉林",  "news_search": "https://www.baidu.com/s?wd=%E5%90%89%E6%9E%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "黑龙江", "news_search": "https://www.baidu.com/s?wd=%E9%BB%91%E9%BE%99%E6%B1%9F+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "山西",  "news_search": "https://www.baidu.com/s?wd=%E5%B1%B1%E8%A5%BF+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "贵州",  "news_search": "https://www.baidu.com/s?wd=%E8%B4%B5%E5%B7%9E+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "云南",  "news_search": "https://www.baidu.com/s?wd=%E4%BA%91%E5%8D%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "广西",  "news_search": "https://www.baidu.com/s?wd=%E5%B9%BF%E8%A5%BF+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "甘肃",  "news_search": "https://www.baidu.com/s?wd=%E7%94%98%E8%82%83+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "内蒙古", "news_search": "https://www.baidu.com/s?wd=%E5%86%85%E8%92%99%E5%8F%A4+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "海南",  "news_search": "https://www.baidu.com/s?wd=%E6%B5%B7%E5%8D%97+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "宁夏",  "news_search": "https://www.baidu.com/s?wd=%E5%AE%81%E5%A4%8F+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "新疆",  "news_search": "https://www.baidu.com/s?wd=%E6%96%B0%E7%96%86+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "青海",  "news_search": "https://www.baidu.com/s?wd=%E9%9D%92%E6%B5%B7+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
    {"name": "西藏",  "news_search": "https://www.baidu.com/s?wd=%E8%A5%BF%E8%97%8F+%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+2025"},
]
cfg.SUBSIDY_KEYWORDS = ["以旧换新", "家电补贴", "国家补贴", "惠民补贴", "消费补贴", "家电下乡", "国补", "京东补贴"]
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
    print(f"  [{n['date']}] {n['title'][:50]}")

print("发送日报...")
for webhook in cfg.DAILY_REPORT_WEBHOOKS:
    bot.notify_subsidy_daily(webhook, news)

print("国补日报发送完成")
