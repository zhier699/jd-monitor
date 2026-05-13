"""
京东商品价格监控 + 飞书通知
- 价格变动 → 通知到对应项目的飞书群（@负责人）
- 每天 09:00 → 国补政策日报发到所有群
"""

import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests
import schedule

import config

# ── 日志 ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("monitor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── 价格缓存（JSON 文件持久化，重启不丢失）──────────────────
CACHE_FILE = Path("price_cache.json")

class PriceCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, float] = {}
        if CACHE_FILE.exists():
            try:
                self._data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                log.info("已从文件加载价格缓存，共 %d 个 SKU", len(self._data))
            except Exception as e:
                log.warning("价格缓存读取失败，从零开始: %s", e)

    def get(self, sku: str) -> float | None:
        return self._data.get(sku)

    def set(self, sku: str, price: float):
        with self._lock:
            self._data[sku] = price
            CACHE_FILE.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


# ── HTTP 工具（带重试）──────────────────────────────────────
def http_get(url: str, params=None, extra_headers=None, timeout=15) -> requests.Response | None:
    headers = {**config.REQUEST_HEADERS, **(extra_headers or {})}
    for attempt in range(1, config.RETRY_TIMES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            log.warning("请求失败（第 %d 次）%s → %s", attempt, url, e)
            if attempt < config.RETRY_TIMES:
                time.sleep(config.RETRY_DELAY)
    return None


# ════════════════════════════════════════════════════════════
# 模块 1：京东价格获取
#   使用京东公开价格接口 p.3.cn，本机直连无需登录
# ════════════════════════════════════════════════════════════
class JDPriceFetcher:
    PRICE_API = "https://p.3.cn/prices/mgets"

    def get_price(self, sku: str) -> float | None:
        """返回当前京东到手价（单位：元）"""
        resp = http_get(self.PRICE_API, params={"skuIds": f"J_{sku}"})
        if not resp:
            return None
        try:
            data = resp.json()
            # p = 现价，op = 原价；优先取现价
            raw = data[0].get("p") or data[0].get("op")
            return float(raw) if raw else None
        except Exception as e:
            log.error("价格解析失败 SKU=%s: %s", sku, e)
            return None


# ════════════════════════════════════════════════════════════
# 模块 2：国补政策抓取
#   数据源：Google News RSS（免费、无需注册、实时收录新华网/21财经/财新等权威媒体）
#   策略：多关键词查询 → 去重 → 按时间排序 → 最多返回 6 条
#   备用：返回空列表，日报降级为纯链接模式
# ════════════════════════════════════════════════════════════
class SubsidyFetcher:

    RSS_BASE = "https://news.google.com/rss/search?hl=zh-CN&gl=CN&ceid=CN:zh-Hans&q={query}"

    # 搜索关键词组合（分两次查，取并集，覆盖更广）
    SEARCH_QUERIES = [
        "以旧换新 家电补贴",
        "国补政策 2025",
    ]

    def fetch_news(self) -> list[dict]:
        """从 Google News RSS 抓取最新国补相关新闻，失败则返回空列表"""
        all_items: list[dict] = []
        cutoff = datetime.now() - timedelta(days=3)  # 只取3天内新闻

        for q in self.SEARCH_QUERIES:
            url = self.RSS_BASE.format(query=quote(q))
            try:
                items = self._parse_rss(url, cutoff)
                all_items.extend(items)
                log.info("Google News RSS [%s] 获取 %d 条", q, len(items))
            except Exception as e:
                log.warning("Google News RSS 失败 [%s]: %s", q, e)

        # 去重（按标题）+ 按时间倒序 + 取前 6 条
        seen: set[str] = set()
        unique: list[dict] = []
        for item in all_items:
            key = item["title"][:30]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        unique.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return unique[:6]

    def _parse_rss(self, url: str, cutoff: datetime) -> list[dict]:
        resp = http_get(url, timeout=15)
        if not resp:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            log.warning("RSS 解析失败: %s", e)
            return []

        results = []
        for item in root.findall(".//item"):
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link")  or "").strip()
            pub_raw = (item.findtext("pubDate") or "").strip()
            source  = (item.findtext("source") or "").strip()

            # Google News 标题格式：「标题 - 媒体名」，去掉后缀
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()

            # 关键词过滤
            if not any(kw in title for kw in config.SUBSIDY_KEYWORDS):
                continue

            # 时间解析
            pub_time = None
            ts = 0
            if pub_raw:
                try:
                    pub_time = parsedate_to_datetime(pub_raw).replace(tzinfo=None)
                    ts = pub_time.timestamp()
                except Exception:
                    pass

            if pub_time and pub_time < cutoff:
                continue

            results.append({
                "source":    source or "Google News",
                "title":     title,
                "link":      link,
                "date":      pub_time.strftime("%m-%d %H:%M") if pub_time else "近期",
                "timestamp": ts,
            })

        return results


# ════════════════════════════════════════════════════════════
# 模块 3：飞书机器人通知
#   Webhook 自定义机器人，文本消息格式
# ════════════════════════════════════════════════════════════
class FeishuBot:

    def _send(self, webhook: str, text: str) -> bool:
        body = {"msg_type": "text", "content": {"text": text}}
        for attempt in range(1, config.RETRY_TIMES + 1):
            try:
                resp = requests.post(webhook, json=body, timeout=10)
                data = resp.json()
                # 飞书自定义机器人 Webhook 成功时返回 {"code": 0, "msg": "success"}
                if data.get("code") == 0:
                    return True
                log.warning("飞书返回非零状态: %s", data)
            except Exception as e:
                log.warning("飞书发送失败（第 %d 次）: %s", attempt, e)
                if attempt < config.RETRY_TIMES:
                    time.sleep(3)
        return False

    # ── 降价通知 ──────────────────────────────────────────
    def notify_price_down(self, webhook: str, project: str, owner: str,
                          sku: str, name: str, old: float, new: float):
        diff = old - new
        pct  = diff / old * 100
        msg = (
            f"🟢 【降价提醒】- {project}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 商品：{name}\n"
            f"💰 价格：{old:.2f}元 → {new:.2f}元\n"
            f"📉 降幅：{diff:.2f}元（{pct:.1f}%）\n"
            f"👤 负责人：@{owner}\n"
            f"🔗 链接：https://item.jd.com/{sku}.html\n"
            f"⏰ 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._send(webhook, msg)

    # ── 涨价通知 ──────────────────────────────────────────
    def notify_price_up(self, webhook: str, project: str, owner: str,
                        sku: str, name: str, old: float, new: float):
        diff = new - old
        pct  = diff / old * 100
        msg = (
            f"🔴 【涨价提醒】- {project}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📦 商品：{name}\n"
            f"💰 价格：{old:.2f}元 → {new:.2f}元\n"
            f"📈 涨幅：{diff:.2f}元（{pct:.1f}%）\n"
            f"👤 负责人：@{owner}\n"
            f"🔗 链接：https://item.jd.com/{sku}.html\n"
            f"⏰ 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._send(webhook, msg)

    # ── 国补日报 ──────────────────────────────────────────
    def notify_subsidy_daily(self, webhook: str, news_items: list[dict]):
        today = datetime.now().strftime("%Y-%m-%d")

        # 新闻部分
        if news_items:
            news_lines = "\n".join(
                f"  [{n['date']}] {n['title']}\n  {n['link']}"
                for n in news_items
            )
        else:
            news_lines = "  近 48 小时内暂无国补政策新动态"

        # 各地区查询入口
        region_lines = "\n".join(
            f"  • {r['name']}：{r['query_url']}"
            for r in config.REGIONS
        )

        msg = (
            f"🔵 【国补政策日报】{today}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 数据来源：国务院 / 商务部 官方 RSS\n\n"
            f"📰 最新政策动态：\n"
            f"{news_lines}\n\n"
            f"🏠 各地区补贴查询入口：\n"
            f"{region_lines}\n\n"
            f"💡 提示：以旧换新国补最高补贴 15%，上限 2000元/件\n"
            f"@所有人"
        )
        self._send(webhook, msg)


# ════════════════════════════════════════════════════════════
# 模块 4：定时任务
# ════════════════════════════════════════════════════════════
cache   = PriceCache()
jd      = JDPriceFetcher()
bot     = FeishuBot()
subsidy = SubsidyFetcher()

# 用锁防止价格任务执行时间过长导致任务堆叠
_price_lock = threading.Lock()


def job_check_prices():
    """每 N 分钟：轮询所有项目的 SKU 价格，有变动则通知"""
    if not _price_lock.acquire(blocking=False):
        log.warning("上次价格检测尚未完成，跳过本轮")
        return
    try:
        log.info("=== 开始价格检测 ===")
        for project in config.PROJECTS:
            proj_name = project["name"]
            webhook   = project["webhook"]
            owner     = project["owner"]

            for item in project["skus"]:
                sku  = item["sku"]
                name = item["name"]

                new_price = jd.get_price(sku)
                if new_price is None:
                    log.warning("[%s] SKU %s 价格获取失败，跳过", proj_name, sku)
                    continue

                old_price = cache.get(sku)
                cache.set(sku, new_price)

                if old_price is None:
                    log.info("[%s] %s（%s）初始价格 %.2f 元", proj_name, name, sku, new_price)
                    continue

                if new_price < old_price:
                    log.info("[%s] %s 降价 %.2f → %.2f", proj_name, name, old_price, new_price)
                    bot.notify_price_down(webhook, proj_name, owner, sku, name, old_price, new_price)
                elif new_price > old_price:
                    log.info("[%s] %s 涨价 %.2f → %.2f", proj_name, name, old_price, new_price)
                    bot.notify_price_up(webhook, proj_name, owner, sku, name, old_price, new_price)
                else:
                    log.debug("[%s] %s 价格无变化 %.2f", proj_name, name, new_price)

        log.info("=== 价格检测完成 ===")
    finally:
        _price_lock.release()


def job_subsidy_daily():
    """每天 09:00：抓取国补新闻，生成日报发到所有群"""
    log.info("=== 发送国补日报 ===")
    news = subsidy.fetch_news()
    log.info("共获取 %d 条国补新闻", len(news))
    for webhook in config.DAILY_REPORT_WEBHOOKS:
        bot.notify_subsidy_daily(webhook, news)


# ════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════
def main():
    log.info("京东商品监控系统启动")
    log.info(
        "监控 %d 个项目，共 %d 个 SKU",
        len(config.PROJECTS),
        sum(len(p["skus"]) for p in config.PROJECTS),
    )

    # 启动时立即跑一次，建立初始价格基准（不通知）
    job_check_prices()

    # 注册定时任务
    schedule.every(config.PRICE_INTERVAL_MIN).minutes.do(job_check_prices)
    schedule.every().day.at(
        f"{config.DAILY_REPORT_HOUR:02d}:00"
    ).do(job_subsidy_daily)

    log.info(
        "任务已注册：价格检测每 %d 分钟 | 国补日报每天 %02d:00",
        config.PRICE_INTERVAL_MIN,
        config.DAILY_REPORT_HOUR,
    )

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
