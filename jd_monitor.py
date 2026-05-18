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
    BATCH_SIZE = 20  # 每次批量查询的 SKU 数量

    def get_prices_batch(self, skus: list[str]) -> dict[str, float]:
        """批量查询多个 SKU 的价格，返回 {sku: price} 字典"""
        result = {}
        for i in range(0, len(skus), self.BATCH_SIZE):
            batch = skus[i: i + self.BATCH_SIZE]
            ids = ",".join(f"J_{s}" for s in batch)
            resp = http_get(self.PRICE_API, params={"skuIds": ids})
            if not resp:
                continue
            try:
                for item in resp.json():
                    # id 字段是 "J_XXXXXX"
                    raw_id = item.get("id", "").replace("J_", "")
                    raw_p  = item.get("p") or item.get("op")
                    if raw_id and raw_p:
                        result[raw_id] = float(raw_p)
            except Exception as e:
                log.error("批量价格解析失败: %s", e)
        return result

    def get_price(self, sku: str) -> float | None:
        """单个 SKU 查询（兼容旧接口）"""
        prices = self.get_prices_batch([sku])
        return prices.get(sku)


# ════════════════════════════════════════════════════════════
# 模块 2：国补政策抓取
#   数据源：36kr RSS（境外服务器和国内均可访问，链接直指国内新闻页面）
#   日报消息固定包含百度新闻搜索直链，保证用户在国内能看到实时新闻
# ════════════════════════════════════════════════════════════
class SubsidyFetcher:
    # 36kr 综合 RSS（境外可访问，链接为 36kr.com，国内无需 VPN）
    RSS_SOURCES = [
        "https://36kr.com/feed",
        "https://www.huxiu.com/rss/0.xml",
    ]

    def fetch_news(self) -> list[dict]:
        """从 36kr/虎嗅 RSS 中筛选国补相关文章，失败返回空列表"""
        all_items: list[dict] = []
        cutoff = datetime.now() - timedelta(days=7)

        for rss_url in self.RSS_SOURCES:
            try:
                items = self._parse_rss(rss_url, cutoff)
                all_items.extend(items)
                log.info("RSS [%s] 获取国补相关 %d 条", rss_url, len(items))
            except Exception as e:
                log.warning("RSS 获取失败 [%s]: %s", rss_url, e)

        # 去重（按标题前30字）+ 按时间倒序 + 取前 5 条
        seen: set[str] = set()
        unique: list[dict] = []
        for item in all_items:
            key = item["title"][:30]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        unique.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return unique[:5]

    def _parse_rss(self, url: str, cutoff: datetime) -> list[dict]:
        resp = http_get(url, timeout=15)
        if not resp:
            return []

        content = resp.content
        # 剥离 BOM
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            log.warning("RSS 解析失败 [%s]: %s", url, e)
            return []

        results = []
        for item in root.findall(".//item"):
            # 处理 CDATA 标题
            title_el = item.find("title")
            title = ""
            if title_el is not None:
                title = (title_el.text or "").strip()

            link    = (item.findtext("link") or item.findtext("guid") or "").strip()
            pub_raw = (item.findtext("pubDate") or "").strip()

            # 关键词过滤（匹配任意一个即可）
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

        # ── 京东平台以旧换新总入口 ──
        jd_entry = (
            "  🛒 京东以旧换新专区（直达）：\n"
            "  https://pro.jd.com/mall/active/3GkqSdBcCBhXDLkJBBUPaXf3e6xd/index.html\n"
            "  🔍 在京东搜「以旧换新国补」：\n"
            "  https://search.jd.com/Search?keyword=%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0%E5%9B%BD%E8%A1%A5&enc=utf-8"
        )

        # ── 各地区京东国补政策新闻入口（百度新闻，国内直接打开）──
        region_lines = "\n".join(
            f"  • {r['name']}：{r['news_search']}"
            for r in config.REGIONS
        )

        # ── 今日最新京东国补资讯（百度新闻，国内直接打开）──
        news_search = (
            "  https://news.baidu.com/s?word=%E4%BA%AC%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0+%E5%9B%BD%E8%A1%A5+2025"
        )

        # ── 自动抓取的最新资讯（有则追加，最多3条）──
        news_block = ""
        if news_items:
            news_lines = "\n".join(
                f"  [{n['date']}] {n['title']}\n  {n['link']}"
                for n in news_items[:3]
            )
            news_block = f"\n📰 今日相关资讯（自动抓取）：\n{news_lines}\n"

        msg = (
            f"🔵 【京东国补日报】{today}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 以旧换新国补：最高补贴 15%，上限 2000元/件\n"
            f"    家电、手机、电脑均可享，旧机核销后自动抵扣\n\n"
            f"🛒 京东平台入口：\n"
            f"{jd_entry}\n\n"
            f"📍 各地区京东国补查询：\n"
            f"{region_lines}\n"
            f"{news_block}\n"
            f"🔍 今日最新国补资讯：\n"
            f"{news_search}\n\n"
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
