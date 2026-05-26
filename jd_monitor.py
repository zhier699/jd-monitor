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
#   步骤1：从任意商品页面提取当前平台国补活动入口URL（任何IP均可）
#   步骤2：调用 cd.jd.com 促销接口拿各品牌具体优惠描述（需中国IP）
#   活动URL存入缓存，次日对比，有变动则标注"政策已更新"
# ════════════════════════════════════════════════════════════
class JDActivityFetcher:
    PROMO_API      = "https://cd.jd.com/promotion/v2"
    ITEM_URL       = "https://item.jd.com/{sku}.html"
    SUBSIDY_KW     = ["国补", "国家补贴", "以旧换新", "国家以旧换新", "政府补贴"]
    AREA           = "1_72_2799_0"
    ACTIVITY_CACHE = Path("activity_cache.json")

    # ── 主入口 ────────────────────────────────────────────
    def fetch_brand_subsidy(self, projects: list) -> dict:
        """
        返回:
          activity  : {url, changed}   当前平台国补活动入口
          brands    : [{brand, name, sku, rules}]  各品牌详情
        """
        # Step1：从第一个品牌第一个 SKU 的商品页面提取活动 URL
        activity = self._get_platform_activity(projects)

        # Step2：逐品牌查促销接口获取具体描述
        brands = []
        for project in projects:
            brand = project["name"]
            found = None
            for item in project["skus"][:10]:
                sku, name = item["sku"], item["name"]
                rules = self._query_promo_api(sku)
                if rules:
                    found = {"brand": brand, "name": name, "sku": sku, "rules": rules}
                    log.info("[%s] %s 促销接口有国补：%s", brand, name, rules[0][:50])
                    break
            if not found:
                # 促销接口没拿到，用活动URL推断（页面已确认国补有效）
                first = project["skus"][0] if project["skus"] else {}
                found = {
                    "brand": brand,
                    "name":  first.get("name", ""),
                    "sku":   first.get("sku", ""),
                    "rules": ["国家补贴活动进行中（详见活动页面）"] if activity.get("url") else [],
                }
                log.info("[%s] 促销接口无数据，依据活动URL推断", brand)
            brands.append(found)

        return {"activity": activity, "brands": brands}

    # ── Step1：提取平台级国补活动URL ──────────────────────
    def _get_platform_activity(self, projects: list) -> dict:
        """从商品页面 HTML 中提取国补活动 URL，并与昨日缓存对比"""
        url = ""
        changed = False
        try:
            sku = projects[0]["skus"][0]["sku"]
            resp = http_get(
                self.ITEM_URL.format(sku=sku),
                extra_headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=15,
            )
            if resp:
                html = resp.text
                # 找所有 pro.jd.com/mall/active/... 链接
                urls = list(dict.fromkeys(re.findall(
                    r'https://pro\.jd\.com/mall/active/\w+/index\.html', html
                )))
                # 优先取 aria-lable="国家补贴" 对应的链接
                guobao = re.findall(
                    r'(https://pro\.jd\.com/mall/active/\w+/index\.html)'
                    r'[^>]*aria-la[b]le=\"国家补贴\"',
                    html,
                )
                url = guobao[0] if guobao else (urls[0] if urls else "")
                log.info("平台国补活动URL: %s", url)

                # 与缓存对比
                old = ""
                if self.ACTIVITY_CACHE.exists():
                    old = json.loads(self.ACTIVITY_CACHE.read_text(encoding="utf-8")).get("url", "")
                changed = bool(old and old != url)
                self.ACTIVITY_CACHE.write_text(
                    json.dumps({"url": url, "date": datetime.now().strftime("%Y-%m-%d")},
                               ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception as e:
            log.warning("获取平台活动URL失败: %s", e)
        return {"url": url, "changed": changed}

    # ── Step2：促销接口（中国IP返回JSON，海外IP返回HTML被忽略）──
    def _query_promo_api(self, sku: str) -> list[str]:
        resp = http_get(
            self.PROMO_API,
            params={"skuId": sku, "area": self.AREA, "num": "1"},
            timeout=10,
        )
        if not resp:
            return []
        raw = resp.text
        # 海外IP或被拦截时返回 HTML，直接跳过
        if raw.strip().startswith("<"):
            return []
        try:
            data = resp.json()
            rules: list[str] = []

            def _dig(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k in ("rule", "title", "content", "desc", "label",
                                 "wording", "tips", "memo", "remark", "promotionInfo"):
                            val = str(v or "").strip()
                            if val and any(kw in val for kw in self.SUBSIDY_KW):
                                rules.append(val)
                        else:
                            _dig(v)
                elif isinstance(obj, list):
                    for i in obj:
                        _dig(i)

            _dig(data)
            if not rules:
                snippets = re.findall(r'(?:国补|以旧换新|国家补贴)[^\n"<]{0,50}', raw)
                rules = list(dict.fromkeys(snippets))[:3]
            return rules
        except Exception as e:
            log.warning("促销接口解析失败 SKU=%s: %s", sku, e)
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
    def notify_subsidy_daily(self, webhook: str, data: dict):
        """
        data: JDActivityFetcher.fetch_brand_subsidy() 返回值
          {"activity": {url, changed}, "brands": [{brand, name, sku, rules}]}
        """
        today    = datetime.now().strftime("%Y-%m-%d")
        activity = data.get("activity", {})
        brands   = data.get("brands", [])

        # ── 平台活动状态 ──────────────────────────────────
        act_url  = activity.get("url", "")
        changed  = activity.get("changed", False)
        if act_url:
            change_tag = "⚠️ 活动链接有更新！请关注政策变化\n" if changed else ""
            act_block = (
                f"✅ 京东国补活动进行中\n"
                f"{change_tag}"
                f"  🔗 今日活动入口（点击直达）：\n"
                f"  {act_url}"
            )
        else:
            act_block = "⚠️ 今日未抓取到国补活动链接，请手动确认"

        # ── 各品牌详情 ────────────────────────────────────
        brand_lines = []
        for item in brands:
            brand = item["brand"]
            if item["rules"]:
                brand_lines.append(f"  ✅ {brand}：{item['rules'][0][:40]}")
                if len(item["rules"]) > 1:
                    for r in item["rules"][1:3]:
                        brand_lines.append(f"       {r[:40]}")
                if item["sku"]:
                    brand_lines.append(f"     → https://item.jd.com/{item['sku']}.html")
            else:
                brand_lines.append(f"  ⚪ {brand}：未查到具体优惠描述")

        # ── 各地区查询 ────────────────────────────────────
        region_lines = "\n".join(
            f"  • {r['name']}：{r['news_search']}"
            for r in config.REGIONS
        )

        msg = (
            f"🔵 【京东国补日报】{today}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 以旧换新：最高补贴 15%，上限 2000元/件\n\n"
            f"🏷️ 今日平台国补状态（直接从京东获取）：\n"
            f"{act_block}\n\n"
            f"📦 各品牌国补详情：\n"
            f"{chr(10).join(brand_lines)}\n\n"
            f"📍 各地区政策查询：\n"
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
