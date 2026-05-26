@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo =============================================
echo  测试：从京东直接抓取国补活动
echo =============================================
echo.
python -X utf8 -c "
import sys, types, json, re, requests

cfg = types.ModuleType('config')
cfg.RETRY_TIMES = 2
cfg.RETRY_DELAY = 2
cfg.REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://www.jd.com/',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
sys.modules['config'] = cfg

from jd_monitor import JDActivityFetcher

data = json.load(open('projects.json', encoding='utf-8'))
fetcher = JDActivityFetcher()

print('--- 逐品牌查询国补（每品牌取第1个SKU测试）---')
for proj in data['projects']:
    brand = proj['name']
    if not proj['skus']:
        continue
    item = proj['skus'][0]
    sku, name = item['sku'], item['name']
    print(f'正在查 [{brand}] {name}（SKU: {sku}）...')

    # 方式A：促销API
    resp_a = requests.get(
        'https://cd.jd.com/promotion/v2',
        params={'skuId': sku, 'area': '1_72_2799_0', 'cat': '1', 'num': '1'},
        headers=cfg.REQUEST_HEADERS,
        proxies={'http': None, 'https': None},
        timeout=10,
    )
    print(f'  促销API状态: {resp_a.status_code}')
    raw = resp_a.text[:500]
    has_kw = any(kw in raw for kw in ['国补','以旧换新','国家补贴'])
    print(f'  含国补关键词: {has_kw}')
    print(f'  原始返回(前200字): {raw[:200]}')

    # 方式B：商品页面
    resp_b = requests.get(
        f'https://item.jd.com/{sku}.html',
        headers={**cfg.REQUEST_HEADERS, 'Accept': 'text/html'},
        proxies={'http': None, 'https': None},
        timeout=15,
    )
    snippets = re.findall(r'(?:国补|以旧换新|国家补贴)[^\"<\n\r]{0,50}', resp_b.text)
    snippets = list(dict.fromkeys(snippets))[:3]
    print(f'  商品页面国补: {snippets if snippets else \"未找到\"}')
    print()
"
echo.
pause
