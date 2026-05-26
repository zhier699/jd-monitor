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
from datetime import datetime
from pathlib import Path

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
    # 强制直连，绕过 VPN/系统代理（避免 VPN 开启时 JD 接口被代理到境外 IP 导致失败）
    NO_PROXY = {"http": None, "https": None}
    for attempt in range(1, config.RETRY_TIMES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers,
                                timeout=timeout, proxies=NO_PROXY)
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
# 模块 2：京东国补活动抓取
#   直接调用京东促销接口，查询监控 SKU 上挂载的国补/以旧换新活动
#   无需依赖外部新闻网站，数据来自京东官方
# ════════════════════════════════════════════════════════════
class JDActivityFetcher:
    PROMO_API  = "https://cd.jd.com/promotion/v2"
    # 国补相关关键词（用于在促销描述中识别国补信息）
    SUBSIDY_KW = ["国补", "国家补贴", "以旧换新", "国家以旧换新", "政府补贴"]
    # 抽查的地区 area 代码（国补为全国统一政策，查一个地区即可）
    AREA       = "1_72_2799_0"   # 北京

    def fetch_brand_subsidy(self, projects: list) -> list[dict]:
        """
        遍历各品牌，取前几个 SKU 查询京东促销接口，
        找到含国补信息的就记录，返回 [{brand, name, sku, rules}]
        """
        results = []
        for project in projects:
            brand = project["name"]
            found = False
            # 每品牌最多查前 5 个 SKU，找到国补就停
            for item in project["skus"][:5]:
                sku  = item["sku"]
                name = item["name"]
                rules = self._query_promo(sku)
                subsidy_rules = [r for r in rules if any(kw in r for kw in self.SUBSIDY_KW)]
                if subsidy_rules:
                    results.append({
                        "brand": brand,
                        "name":  name,
                        "sku":   sku,
                        "rules": subsidy_rules,
                    })
                    log.info("[%s] %s 有国补活动：%s", brand, name, subsidy_rules)
                    found = True
                    break
            if not found:
                log.info("[%s] 前5个SKU均未查到国补活动", brand)
                results.append({
                    "brand": brand,
                    "name":  "",
                    "sku":   "",
                    "rules": [],
                })
        return results

    def _query_promo(self, sku: str) -> list[str]:
        """查询单个 SKU 的京东促销信息，返回所有促销描述文本列表"""
        resp = http_get(
            self.PROMO_API,
            params={"skuId": sku, "area": self.AREA, "cat": "1", "num": "1"},
            timeout=10,
        )
        if not resp:
            return []
        try:
            data = resp.json()
            rules: list[str] = []
            # 常见字段：promotions[].rule / skuCouponActInfoList[].desc
            for promo in data.get("promotions", []):
                for field in ("rule", "title", "content", "desc"):
                    val = str(promo.get(field) or "").strip()
                    if val and val not in rules:
                        rules.append(val)
            for act in data.get("skuCouponActInfoList", []):
                for field in ("desc", "name", "title"):
                    val = str(act.get(field) or "").strip()
                    if val and val not in rules:
                        rules.append(val)
            # 如果结构未知但原始字符串中含关键词，兜底记录
            raw = json.dumps(data, ensure_ascii=False)
            if not rules and any(kw in raw for kw in self.SUBSIDY_KW):
                # 用正则从 JSON 中提取含关键词的短句
                snippets = re.findall(r'[^"]{0,10}(?:国补|以旧换新|国家补贴)[^"]{0,30}', raw)
                rules = list(dict.fromkeys(snippets))[:3]
            log.debug("SKU %s 促销原始: %s", sku, raw[:300])
            return rules
        except Exception as e:
            log.warning("SKU %s 促销解析失败: %s", sku, e)
            return []


# ════════════════════════════════════════════════════════════
# 模块 3：飞书机器人通知
#   Webhook 自定义机器人，文本消息格式
# ════════════════════════════════════════════════════════════
class FeishuBot:

    def _send(self, webhook: str, text: str) -> bool:
        body = {"msg_type": "text", "content": {"text": text}}
        NO_PROXY = {"http": None, "https": None}
        for attempt in range(1, config.RETRY_TIMES + 1):
            try:
                resp = requests.post(webhook, json=body, timeout=10, proxies=NO_PROXY)
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
    def notify_subsidy_daily(self, webhook: str, brand_data: list[dict]):
        """
        brand_data: JDActivityFetcher.fetch_brand_subsidy() 返回值
        [{brand, name, sku, rules}]
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # ── 各品牌国补活动汇总 ────────────────────────────
        brand_lines = []
        has_subsidy = False
        for item in brand_data:
            brand = item["brand"]
            if item["rules"]:
                has_subsidy = True
                brand_lines.append(f"  ✅ {brand}（{item['name']}）")
                for r in item["rules"][:3]:
                    brand_lines.append(f"     → {r}")
                brand_lines.append(f"     🔗 https://item.jd.com/{item['sku']}.html")
            else:
                brand_lines.append(f"  ⚪ {brand}：当前未查到国补活动")

        subsidy_block = "\n".join(brand_lines)

        # ── 各地区查询入口 ────────────────────────────────
        region_lines = "\n".join(
            f"  • {r['name']}：{r['news_search']}"
            for r in config.REGIONS
        )

        status = "📢 今日有品牌享有国补，详见下方" if has_subsidy else "📢 今日所监控商品暂未查到国补活动"

        msg = (
            f"🔵 【京东国补日报】{today}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 以旧换新国补：最高补贴 15%，上限 2000元/件\n"
            f"{status}\n\n"
            f"🏷️ 监控品牌国补状态（直接从京东抓取）：\n"
            f"{subsidy_block}\n\n"
            f"🛒 京东以旧换新专区：\n"
            f"  https://search.jd.com/Search?keyword=%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0%E5%9B%BD%E8%A1%A5&enc=utf-8\n\n"
            f"📍 各地区国补政策查询：\n"
            f"{region_lines}\n\n"
            f"@所有人"
        )
        self._send(webhook, msg)


# ════════════════════════════════════════════════════════════
# 模块 4：定时任务
# ════════════════════════════════════════════════════════════
cache      = PriceCache()
jd         = JDPriceFetcher()
bot        = FeishuBot()
jd_activity = JDActivityFetcher()

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
    """每天 09:00：直接从京东抓取各品牌国补活动，发日报到所有群"""
    log.info("=== 发送国补日报 ===")
    brand_data = jd_activity.fetch_brand_subsidy(config.PROJECTS)
    log.info("国补活动抓取完成，共 %d 个品牌", len(brand_data))
    for webhook in config.DAILY_REPORT_WEBHOOKS:
        bot.notify_subsidy_daily(webhook, brand_data)


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
