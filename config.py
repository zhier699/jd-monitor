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

# ── 京东各地区国补入口 ──────────────────────────────────────
# jd_search : 该省在京东上搜索以旧换新的直达链接（稳定可访问）
# official  : 该省官方政府补贴查询页（真实存在的 URL）
REGIONS = [
    {
        "name": "北京",
        "jd_search": "https://search.jd.com/Search?keyword=%E5%8C%97%E4%BA%AC+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "https://www.beijing.gov.cn/zhengce/zhengcefagui/",
    },
    {
        "name": "上海",
        "jd_search": "https://search.jd.com/Search?keyword=%E4%B8%8A%E6%B5%B7+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "https://www.shanghai.gov.cn/nw4411/index.html",
    },
    {
        "name": "广东",
        "jd_search": "https://search.jd.com/Search?keyword=%E5%B9%BF%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "http://commerce.gd.gov.cn/",
    },
    {
        "name": "浙江",
        "jd_search": "https://search.jd.com/Search?keyword=%E6%B5%99%E6%B1%9F+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "https://www.zj.gov.cn/col/col1229560015/index.html",
    },
    {
        "name": "江苏",
        "jd_search": "https://search.jd.com/Search?keyword=%E6%B1%9F%E8%8B%8F+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "http://commerce.jiangsu.gov.cn/",
    },
    {
        "name": "四川",
        "jd_search": "https://search.jd.com/Search?keyword=%E5%9B%9B%E5%B7%9D+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "https://www.sc.gov.cn/10462/c105960/list.shtml",
    },
    {
        "name": "湖北",
        "jd_search": "https://search.jd.com/Search?keyword=%E6%B9%96%E5%8C%97+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "http://swt.hubei.gov.cn/",
    },
    {
        "name": "山东",
        "jd_search": "https://search.jd.com/Search?keyword=%E5%B1%B1%E4%B8%9C+%E4%BB%A5%E6%97%A7%E6%8D%A2%E6%96%B0&enc=utf-8",
        "official":  "http://commerce.shandong.gov.cn/",
    },
]

# 国补相关关键词（RSS 文章标题过滤用）
SUBSIDY_KEYWORDS = ["以旧换新", "家电补贴", "国家补贴", "惠民补贴", "消费补贴", "家电下乡", "国补", "京东补贴"]

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
