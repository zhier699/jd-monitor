# ============================================================
# 京东商品监控系统 - 配置文件
# 填写你的飞书 Webhook 和商品信息即可运行
# ============================================================

# ────────────────────────────────────────────────────────────
# 项目配置
# 每个项目配置自己的飞书群 Webhook + 负责人 + SKU 列表
# 价格变动时只通知对应项目的群，不打扰其他项目
# ────────────────────────────────────────────────────────────
PROJECTS = [
    {
        "name": "项目A",
        "owner": "张三",    # 飞书显示名，用于消息中 @
        "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/替换为项目A的Webhook",
        "skus": [
            {"sku": "100012043978", "name": "示例商品-请替换为真实商品名"},
            # 继续添加本项目的 SKU：
            # {"sku": "100xxxxxxxxx", "name": "商品名称"},
        ],
    },
    {
        "name": "项目B",
        "owner": "李四",
        "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/替换为项目B的Webhook",
        "skus": [
            {"sku": "填入SKU", "name": "商品名称"},
        ],
    },
    # 继续添加项目：
    # {
    #     "name": "项目C",
    #     "owner": "王五",
    #     "webhook": "https://open.feishu.cn/...",
    #     "skus": [...],
    # },
]

# ────────────────────────────────────────────────────────────
# 国补日报配置
# 日报默认发到所有项目群；如果有单独汇总群，把 Webhook 加到下面
# ────────────────────────────────────────────────────────────
DAILY_REPORT_WEBHOOKS = [p["webhook"] for p in PROJECTS]

# 各地区官方国补政策入口（政府官网，稳定可访问）
# 日报会把这些链接一并发出，方便点进去查最新补贴金额
REGIONS = [
    {
        "name": "北京",
        "url": "http://swj.beijing.gov.cn/zwgk/zcwj/",
        "query_url": "https://bjsubsidy.mofcom.gov.cn/",   # 北京以旧换新查询
    },
    {
        "name": "上海",
        "url": "http://sww.sh.gov.cn/shswzc/",
        "query_url": "https://shsubsidy.mofcom.gov.cn/",
    },
    {
        "name": "广东",
        "url": "http://commerce.gd.gov.cn/gkmlpt/index",
        "query_url": "https://gdsubsidy.mofcom.gov.cn/",
    },
    {
        "name": "浙江",
        "url": "http://com.zj.gov.cn/col/col1229560014/",
        "query_url": "https://zjsubsidy.mofcom.gov.cn/",
    },
    {
        "name": "江苏",
        "url": "http://commerce.jiangsu.gov.cn/col/col79408/",
        "query_url": "https://jssubsidy.mofcom.gov.cn/",
    },
    {
        "name": "四川",
        "url": "http://scsw.sc.gov.cn/scsw/zcwj/",
        "query_url": "https://scsubsidy.mofcom.gov.cn/",
    },
]

# 国补相关关键词（文章标题包含这些词才纳入日报）
# gov.cn / mofcom.gov.cn 已停止 RSS 服务，改为直接抓取文章列表页
SUBSIDY_KEYWORDS = ["以旧换新", "家电补贴", "国家补贴", "惠民补贴", "新能源补贴", "消费补贴", "家电下乡", "国补"]

# ────────────────────────────────────────────────────────────
# 监控频率
# ────────────────────────────────────────────────────────────
PRICE_INTERVAL_MIN = 5    # 价格轮询间隔（分钟）
DAILY_REPORT_HOUR  = 9    # 国补日报发送时间（整点，24小时制）

# ────────────────────────────────────────────────────────────
# HTTP 请求配置
# ────────────────────────────────────────────────────────────
RETRY_TIMES = 3
RETRY_DELAY = 5   # 秒

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.jd.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
