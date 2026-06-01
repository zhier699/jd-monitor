"""
国补日报入口
支持本地运行（读 projects.json）和 GitHub Actions（读 PROJECTS_JSON 环境变量）
"""
import json
import logging
import os
import sys
import types
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ── 加载配置：优先环境变量，回退本地文件 ────────────────
raw = os.environ.get("PROJECTS_JSON", "")
if not raw:
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
    print(f"❌ 配置格式错误: {e}")
    sys.exit(1)

# ── 构建 config 模块 ──────────────────────────────────
cfg = types.ModuleType("config")
cfg.PROJECTS              = projects_data["projects"]
cfg.DAILY_REPORT_WEBHOOKS = list(dict.fromkeys(p["webhook"] for p in cfg.PROJECTS))
cfg.PRICE_INTERVAL_MIN    = 5
cfg.DAILY_REPORT_HOUR     = 9
cfg.RETRY_TIMES           = 3
cfg.RETRY_DELAY           = 5
cfg.REQUEST_HEADERS       = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.jd.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
sys.modules["config"] = cfg

from load_sku import merge_projects_with_excel
from jd_monitor import JDActivityFetcher, FeishuBot

# 用桌面 sku.xls 覆盖 projects.json 里的 skus（找不到则回退原配置）
cfg.PROJECTS = merge_projects_with_excel(cfg.PROJECTS)
# 日报 Webhook 根据更新后的品牌列表重新去重
cfg.DAILY_REPORT_WEBHOOKS = list(dict.fromkeys(p["webhook"] for p in cfg.PROJECTS))

bot     = FeishuBot()
fetcher = JDActivityFetcher()

print(f"正在从京东抓取国补活动（共 {len(cfg.PROJECTS)} 个品牌）...")
result = fetcher.fetch_brand_subsidy(cfg.PROJECTS)

act = result.get("activity", {})
print(f"平台活动URL: {act.get('url', '未获取到')}  变化: {act.get('changed', False)}")
for item in result.get("brands", []):
    status = item["rules"][0][:40] if item["rules"] else "未查到具体描述"
    print(f"  [{item['brand']}] {status}")

# ── 面板开关：REPORT_PROVINCE=0 时跳过各地区政策区块 ──
if os.environ.get("REPORT_PROVINCE", "1") != "1":
    result["province_policies"] = None     # None → notify_subsidy_daily 跳过省份区块
    print("📍 各地区政策：已关闭（面板开关）")
else:
    cnt = len(result.get("province_policies") or {})
    if cnt:
        print(f"📍 各地区政策：已提取 {cnt} 个省份政策文字")
    else:
        print("📍 各地区政策：未能提取省份专属文字，将显示通用说明")

print("发送日报...")
for webhook in cfg.DAILY_REPORT_WEBHOOKS:
    bot.notify_subsidy_daily(webhook, result)

print("国补日报发送完成 ✅")
