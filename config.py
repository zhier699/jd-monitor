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

# ── 京东各地区国补入口（全国31个省/直辖市/自治区）──────────────
# news_search : 该省百度新闻搜索，点开看当地京东以旧换新最新政策动态
REGIONS = [
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
