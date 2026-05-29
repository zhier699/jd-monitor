"""
京东商品价格监控 + 飞书通知
- 价格变动 → 通知到对应项目的飞书群（@负责人）
- 每天 09:00 → 国补政策日报发到所有群
"""

import datetime as _datetime_mod
import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

import config  # 由调用脚本（run_*.py）提前注入 sys.modules

# 北京时间 UTC+8
_TZ_BJ = _datetime_mod.timezone(_datetime_mod.timedelta(hours=8))


def _now_bj() -> datetime:
    return datetime.now(_TZ_BJ)

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


# ── HTTP Session（trust_env=False 彻底屏蔽系统/VPN代理）──────
_session = requests.Session()
_session.trust_env = False   # 忽略 HTTP_PROXY / HTTPS_PROXY 环境变量及系统代理


def http_get(url: str, params=None, extra_headers=None, timeout=15) -> requests.Response | None:
    headers = {**config.REQUEST_HEADERS, **(extra_headers or {})}
    for attempt in range(1, config.RETRY_TIMES + 1):
        try:
            resp = _session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as e:
            # 4xx 是客户端/资源问题，重试无意义，直接返回
            if resp.status_code < 500:
                log.warning("请求 %d 错误，不重试 %s → %s", resp.status_code, url, e)
                return None
            log.warning("请求失败（第 %d 次，5xx）%s → %s", attempt, url, e)
        except Exception as e:
            log.warning("请求失败（第 %d 次）%s → %s", attempt, url, e)
        if attempt < config.RETRY_TIMES:
            time.sleep(config.RETRY_DELAY)
    return None


# ════════════════════════════════════════════════════════════
# 模块 1：京东价格获取
#   主路：p.3.cn 批量接口（快，每批20个）
#   备用：item-soa.jd.com 单品接口
#   兜底：item.jd.com 商品页面正则提取
# ════════════════════════════════════════════════════════════
class JDPriceFetcher:
    PRICE_API   = "https://p.3.cn/prices/mgets"
    SOA_API     = "https://item-soa.jd.com/itemInfoGet"
    ITEM_URL    = "https://item.jd.com/{sku}.html"
    BATCH_SIZE  = 20

    def get_prices_batch(self, skus: list[str]) -> dict[str, float]:
        """批量查询价格：先尝试主接口，失败则逐个走备用接口"""
        result = self._batch_p3cn(skus)
        # 对主接口未返回的 SKU 逐个走备用
        missing = [s for s in skus if s not in result]
        if missing:
            log.info("p.3.cn 未返回 %d 个 SKU，走备用接口", len(missing))
            for sku in missing:
                p = self._single_soa(sku) or self._single_page(sku)
                if p is not None:
                    result[sku] = p
        return result

    def _batch_p3cn(self, skus: list[str]) -> dict[str, float]:
        """主接口：批量查询"""
        result = {}
        for i in range(0, len(skus), self.BATCH_SIZE):
            batch = skus[i: i + self.BATCH_SIZE]
            ids   = ",".join(f"J_{s}" for s in batch)
            resp  = http_get(self.PRICE_API, params={"skuIds": ids}, timeout=8)
            if not resp:
                continue
            try:
                for item in resp.json():
                    raw_id = item.get("id", "").replace("J_", "")
                    raw_p  = item.get("p") or item.get("op")
                    if raw_id and raw_p:
                        result[raw_id] = float(raw_p)
            except Exception as e:
                log.warning("p.3.cn 解析失败: %s", e)
        return result

    def _single_soa(self, sku: str) -> float | None:
        """备用接口：item-soa.jd.com"""
        try:
            resp = http_get(self.SOA_API,
                            params={"skuId": sku, "area": "1_72_2799_0"},
                            timeout=10)
            if not resp:
                return None
            raw = resp.text
            if raw.strip().startswith("<"):
                return None
            data = resp.json()
            # 尝试各字段路径
            for path in [["price", "p"], ["defaultPrice"], ["price"]]:
                obj = data
                for k in path:
                    if isinstance(obj, dict):
                        obj = obj.get(k)
                if obj and str(obj).replace(".", "").isdigit():
                    return float(obj)
        except Exception as e:
            log.debug("item-soa 失败 SKU=%s: %s", sku, e)
        return None

    def _single_page(self, sku: str) -> float | None:
        """兜底：从商品页面 HTML 提取价格"""
        try:
            resp = http_get(self.ITEM_URL.format(sku=sku),
                            extra_headers={"Accept": "text/html"},
                            timeout=15)
            if not resp:
                return None
            html = resp.text
            # 尝试多种价格模式
            patterns = [
                r'"defaultPrice"\s*:\s*"([0-9]+\.?[0-9]*)"',
                r'"p"\s*:\s*"([0-9]+\.?[0-9]*)"',
                r'window\.jd_price\s*=\s*([0-9]+\.?[0-9]*)',
                r'class="p-price"[^>]*>[^<]*<[^>]+>([0-9]+\.?[0-9]*)',
            ]
            for pat in patterns:
                m = re.search(pat, html)
                if m:
                    val = float(m.group(1))
                    if val > 0:
                        log.info("页面提取价格 SKU=%s → %.2f", sku, val)
                        return val
        except Exception as e:
            log.debug("页面提取价格失败 SKU=%s: %s", sku, e)
        return None

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

    # 全国31省市（日报各地区入口使用）
    PROVINCES = [
        "北京", "上海", "天津", "重庆",
        "广东", "浙江", "江苏", "山东", "河南", "河北",
        "湖北", "湖南", "四川", "福建", "安徽", "江西",
        "陕西", "辽宁", "吉林", "黑龙江", "山西", "贵州",
        "云南", "广西", "甘肃", "内蒙古", "海南", "宁夏",
        "新疆", "青海", "西藏",
    ]

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

            # 2-A：先试 cd.jd.com 促销接口（最准确）
            for item in project["skus"][:10]:
                sku, name = item["sku"], item["name"]
                rules = self._query_promo_api(sku)
                if rules:
                    found = {"brand": brand, "name": name, "sku": sku, "rules": rules}
                    log.info("[%s] %s 促销接口有国补：%s", brand, name, rules[0][:50])
                    break

            # 2-B：促销接口失败 → 从商品页面 HTML 提取（备用）
            if not found:
                for item in project["skus"][:3]:
                    sku, name = item["sku"], item["name"]
                    rules = self._extract_promo_from_page(sku)
                    if rules:
                        found = {"brand": brand, "name": name, "sku": sku, "rules": rules}
                        log.info("[%s] 从页面提取到国补文字：%s", brand, rules[0][:50])
                        break

            # 2-C：两种方法都失败 → 通用兜底，不显示商品链接
            if not found:
                first = project["skus"][0] if project["skus"] else {}
                found = {
                    "brand": brand,
                    "name":  first.get("name", ""),
                    "sku":   "",   # 清空 SKU，避免在消息里显示商品页链接
                    "rules": ["国家补贴活动进行中"] if activity.get("url") else [],
                }
                log.info("[%s] 未能获取具体国补描述，使用兜底文案", brand)

            brands.append(found)

        # Step3：从主活动页面抓各省国补政策文字
        province_policies = self._get_province_policy_text(activity.get("url", ""))

        return {"activity": activity, "brands": brands, "province_policies": province_policies}

    # ── Step1：提取平台级国补活动URL ──────────────────────
    def _get_platform_activity(self, projects: list) -> dict:
        """从商品页面 HTML 中提取国补活动 URL，并与昨日缓存对比"""
        url = ""
        changed = False
        try:
            if not projects or not projects[0].get("skus"):
                log.warning("_get_platform_activity: projects 为空，跳过")
                return {"url": "", "changed": False}
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

                # 与缓存对比（仅在成功拿到 URL 时才更新缓存，避免请求失败时覆盖历史记录）
                old = ""
                if self.ACTIVITY_CACHE.exists():
                    old = json.loads(self.ACTIVITY_CACHE.read_text(encoding="utf-8")).get("url", "")
                if url:
                    changed = bool(old and old != url)
                    self.ACTIVITY_CACHE.write_text(
                        json.dumps({"url": url, "date": _now_bj().strftime("%Y-%m-%d")},
                                   ensure_ascii=False),
                        encoding="utf-8",
                    )
                else:
                    changed = False  # 请求失败，不判定为变化，也不覆盖缓存
        except Exception as e:
            log.warning("获取平台活动URL失败: %s", e)
        return {"url": url, "changed": changed}

    # ── Step1b：从主活动页面提取各省国补政策文字 ────────────
    def _get_province_policy_text(self, activity_url: str) -> dict[str, str]:
        """
        从主活动页面 HTML 中提取各省份的国补政策文字（补贴比例/金额）。
        策略：
          1. 抓主活动页 HTML，剥离标签得到纯文本
          2. 在每个省份名附近（前80后250字符）搜索含补贴金额/比例的句子
          3. 优先匹配含比例+金额的完整描述，其次含金额，其次含比例
          4. 找不到返回 {}（调用方显示通用说明）
        """
        if not activity_url:
            return {}
        try:
            resp = http_get(
                activity_url,
                extra_headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=15,
            )
            if not resp:
                return {}
            html = resp.text

            # 剥离 HTML 标签、转义字符，得到便于匹配的纯文本
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\\u[0-9a-fA-F]{4}', '', text)
            text = re.sub(r'\s+', ' ', text)

            province_policies: dict[str, str] = {}
            for province in self.PROVINCES:
                best = ""
                for m in re.finditer(re.escape(province), text):
                    pos     = m.start()
                    snippet = text[max(0, pos - 80): pos + 250]
                    hit     = self._extract_subsidy_sentence(snippet)
                    if hit and len(hit) > len(best):
                        best = hit
                if best:
                    province_policies[province] = best

            log.info("省份政策文字提取: %d / %d 个省",
                     len(province_policies), len(self.PROVINCES))
            return province_policies

        except Exception as e:
            log.debug("省份政策文字提取失败: %s", e)
        return {}

    def _extract_subsidy_sentence(self, snippet: str) -> str:
        """
        从文本片段中提取补贴政策描述句子。
        优先级：含比例+金额 > 含金额 > 含比例 > 金额上限
        """
        candidates = [
            # 含比例且含金额：如"补贴15%，上限2000元"
            r'(?:补贴|以旧换新|国补)[^\n。；]{0,50}?\d+(?:\.\d+)?%[^\n。；]{0,50}?\d+[^\n。；]{0,10}元',
            # 仅含金额：如"补贴最高2000元"
            r'(?:补贴|以旧换新|国补)[^\n。；]{0,50}?\d+(?:,\d+)?[^\n。；]{0,10}元',
            # 仅含比例：如"补贴15%"
            r'(?:补贴|以旧换新|国补)[^\n。；]{0,30}?\d+(?:\.\d+)?%',
            # 金额上限：如"上限2000元"
            r'上限\s*\d+(?:,\d+)?\s*元',
        ]
        for pat in candidates:
            m = re.search(pat, snippet)
            if m:
                s = re.sub(r'\s+', ' ', m.group(0)).strip()
                if 4 < len(s) < 80:
                    return s
        return ""

    # ── Step2：促销接口（仅试一次，502/HTML直接跳过不重试）──
    def _query_promo_api(self, sku: str) -> list[str]:
        try:
            resp = _session.get(
                self.PROMO_API,
                params={"skuId": sku, "area": self.AREA, "num": "1"},
                headers=config.REQUEST_HEADERS,
                timeout=8,
            )
        except Exception as e:
            log.debug("促销接口异常 SKU=%s: %s", sku, e)
            return []
        raw = resp.text
        # HTML / 4xx / 5xx → 直接跳过
        if raw.strip().startswith("<") or resp.status_code >= 400:
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

    # ── Step3（备用）：从商品页面 HTML 提取国补文字 ──────────
    def _extract_promo_from_page(self, sku: str) -> list[str]:
        """
        当 cd.jd.com 失败时，从 item.jd.com 商品页面的静态 HTML 中
        搜索含金额的国补/以旧换新文字（如「国家补贴立减200元」）
        """
        try:
            resp = http_get(
                self.ITEM_URL.format(sku=sku),
                extra_headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=15,
            )
            if not resp:
                return []
            html = resp.text
            # 先找带金额的高质量片段，再 fallback 到仅含关键词的片段
            patterns = [
                r'(?:国家补贴|以旧换新|国补)[^\n"<\\]{2,60}?(?:\d+(?:\.\d+)?)\s*元',
                r'(?:国家补贴|以旧换新|国补)[^\n"<\\]{2,50}',
            ]
            found: list[str] = []
            seen: set[str]   = set()
            for pat in patterns:
                for m in re.finditer(pat, html):
                    s = m.group(0).strip()
                    s = re.sub(r'\\u[0-9a-fA-F]{4}', '', s)   # 去掉 unicode escape
                    s = re.sub(r'\s+', ' ', s).strip()
                    if s and s not in seen and 5 < len(s) < 80:
                        seen.add(s)
                        found.append(s)
                if found:
                    break   # 有含金额的结果就不再用宽泛模式
            log.debug("页面促销提取 SKU=%s → %d 条: %s", sku, len(found), found[:2])
            return found[:3]
        except Exception as e:
            log.debug("页面促销提取失败 SKU=%s: %s", sku, e)
        return []


# ════════════════════════════════════════════════════════════
# 模块 3：飞书机器人通知
#   Webhook 自定义机器人，文本消息格式
# ════════════════════════════════════════════════════════════
class FeishuBot:

    def _send(self, webhook: str, text: str) -> bool:
        body = {"msg_type": "text", "content": {"text": text}}
        for attempt in range(1, config.RETRY_TIMES + 1):
            try:
                resp = _session.post(webhook, json=body, timeout=10)
                data = resp.json()
                if data.get("code") == 0:
                    return True
                log.warning("飞书返回非零状态（第 %d 次）: %s", attempt, data)
            except Exception as e:
                log.warning("飞书发送失败（第 %d 次）: %s", attempt, e)
            # 无论是非零返回码还是异常，重试前都等待，避免加速触发限流
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
            f"⏰ 时间：{_now_bj().strftime('%Y-%m-%d %H:%M:%S')}"
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
            f"⏰ 时间：{_now_bj().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._send(webhook, msg)

    # ── 国补日报 ──────────────────────────────────────────
    def notify_subsidy_daily(self, webhook: str, data: dict):
        """
        data: JDActivityFetcher.fetch_brand_subsidy() 返回值
          {"activity": {url, changed},
           "brands": [{brand, name, sku, rules}],
           "province_policies": {省份: 政策文字} | {} | None}
        """
        today    = _now_bj().strftime("%Y-%m-%d")
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
        brand_lines  = []
        has_fallback = False   # 是否有品牌用了兜底文案（无具体金额）
        for item in brands:
            brand = item["brand"]
            if item["rules"]:
                rule_text = item["rules"][0][:40]
                brand_lines.append(f"  ✅ {brand}：{rule_text}")
                if len(item["rules"]) > 1:
                    for r in item["rules"][1:3]:
                        brand_lines.append(f"       {r[:40]}")
                if item["sku"]:
                    # 有真实的 SKU（促销接口或页面提取到的），显示商品直达链接
                    brand_lines.append(f"     → https://item.jd.com/{item['sku']}.html")
                else:
                    # 兜底文案，无商品链接
                    has_fallback = True
            else:
                brand_lines.append(f"  ⚪ {brand}：未查到具体优惠描述")

        # 有兜底品牌且平台活动 URL 存在，则在底部补充引导
        if has_fallback and act_url:
            brand_lines.append(f"  📌 具体补贴金额请点击上方活动入口查看")

        # ── 各地区国补政策文字 ─────────────────────────────────
        # province_policies=None  → 面板开关关闭，跳过此区块
        # province_policies={}    → 未能提取省份文字，显示通用说明
        # province_policies={...} → 有省份专属文字，逐省展示
        province_policies = data.get("province_policies")   # 可能是 None / {} / {省:文字}
        if province_policies is None:
            prov_block = ""   # 面板开关已关，不输出省份区块
        elif province_policies:
            lines = []
            for p in JDActivityFetcher.PROVINCES:
                policy = province_policies.get(p, "与全国政策一致")
                lines.append(f"  • {p}：{policy}")
            prov_block = "📍 各地区国补政策（今日）：\n" + "\n".join(lines)
        else:
            prov_block = "📍 各地区政策：与全国一致，补贴15%，单件上限2000元，具体以活动页面为准"

        parts = [
            f"🔵 【京东国补日报】{today}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "💡 以旧换新：最高补贴 15%，上限 2000元/件",
            "",
            "🏷️ 今日平台国补状态：",
            act_block,
            "",
            "📦 各品牌国补详情：",
            "\n".join(brand_lines),
        ]
        if prov_block:               # 开关打开时才追加省份区块
            parts += ["", prov_block]
        parts += ["", "@所有人"]
        msg = "\n".join(parts)
        self._send(webhook, msg)


# ════════════════════════════════════════════════════════════
# 模块 4：定时任务（仅 __main__ 模式使用，import 时不实例化）
# ════════════════════════════════════════════════════════════
_price_lock = threading.Lock()

# 延迟初始化，import 时不创建实例（避免 run_price_check.py 等脚本重复初始化）
_cache: "PriceCache | None" = None
_jd: "JDPriceFetcher | None" = None
_bot: "FeishuBot | None" = None
_jd_activity: "JDActivityFetcher | None" = None


def _get_singletons():
    global _cache, _jd, _bot, _jd_activity
    if _cache is None:
        _cache       = PriceCache()
        _jd          = JDPriceFetcher()
        _bot         = FeishuBot()
        _jd_activity = JDActivityFetcher()
    return _cache, _jd, _bot, _jd_activity


def job_check_prices():
    """每 N 分钟：轮询所有项目的 SKU 价格，有变动则通知"""
    if not _price_lock.acquire(blocking=False):
        log.warning("上次价格检测尚未完成，跳过本轮")
        return
    cache, jd, bot, _ = _get_singletons()
    try:
        log.info("=== 开始价格检测 ===")
        for project in config.PROJECTS:
            proj_name   = project["name"]
            webhook     = project["webhook"]
            owner       = project["owner"]
            sku_list    = project["skus"]

            # 批量查询本项目所有 SKU（每批20个，大幅减少 API 调用次数）
            all_skus     = [item["sku"] for item in sku_list]
            sku_to_name  = {item["sku"]: item["name"] for item in sku_list}
            prices       = jd.get_prices_batch(all_skus)
            log.info("[%s] 查询 %d 个 SKU，成功返回 %d 个",
                     proj_name, len(all_skus), len(prices))

            for sku, name in sku_to_name.items():
                new_price = prices.get(sku)
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
    _, _, bot, jd_activity = _get_singletons()
    log.info("=== 发送国补日报 ===")
    brand_data = jd_activity.fetch_brand_subsidy(config.PROJECTS)
    log.info("国补活动抓取完成，共 %d 个品牌", len(brand_data.get("brands", [])))
    seen = set()
    for webhook in config.DAILY_REPORT_WEBHOOKS:
        if webhook not in seen:
            seen.add(webhook)
            bot.notify_subsidy_daily(webhook, brand_data)


# ════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════
def main():
    import schedule  # 仅单文件直接运行时需要，面板模式不走此路径
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
