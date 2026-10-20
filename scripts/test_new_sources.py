import os
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)

import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json

# 1. 官方辅助 API - getDigitalDrawInfoV1
print("=" * 60)
print("  1. 官方辅助 API: getDigitalDrawInfoV1.qry")
print("=" * 60)
url1 = "https://webapi.sporttery.cn/gateway/lottery/getDigitalDrawInfoV1.qry"
params1 = {"param": "85,0", "isVerify": "1"}
headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.sporttery.cn/"}
try:
    r = requests.get(url1, params=params1, headers=headers, timeout=10)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code == 200:
        data = r.json()
        if data.get("success"):
            dlt = data.get("value", {}).get("dlt", {})
            print(f"lotteryDrawNum: {dlt.get('lotteryDrawNum')}")
            print(f"lotteryDrawTime: {dlt.get('lotteryDrawTime')}")
            print(f"lotteryDrawResult: {dlt.get('lotteryDrawResult')}")
            print(f"verify: {dlt.get('verify')}")
except Exception as e:
    print(f"FAILED: {e}")

# 2. 官方 lottery.gov.cn 历史页（不是 API，但 JS 渲染）
print()
print("=" * 60)
print("  2. 官方 lottery.gov.cn 历史页")
print("=" * 60)
url2 = "https://www.lottery.gov.cn/kj/kjlb.html?dlt"
try:
    r = requests.get(url2, headers={**headers, "Accept": "text/html"}, timeout=10)
    print(f"HTTP {r.status_code}, len={len(r.text)}, enc={r.apparent_encoding}")
    # 检查 JS 文件
    import re
    js_files = re.findall(r'src="([^"]+\.js)"', r.text)
    print(f"JS files: {js_files[:5]}")
except Exception as e:
    print(f"FAILED: {e}")

# 3. static.sporttery.cn 静态资源
print()
print("=" * 60)
print("  3. static.sporttery.cn 静态资源")
print("=" * 60)
js_urls = [
    "https://static.sporttery.cn/res_1_0/jcw/default/kj/dltKj.js",
    "https://static.sporttery.cn/res_1_0/jcw/default/kj/kjCommonFun.js",
]
for u in js_urls:
    try:
        r = requests.get(u, headers=headers, timeout=10)
        print(f"  {u[-50:]:50s} HTTP {r.status_code} len={len(r.text)}")
    except Exception as e:
        print(f"  {u[-50:]:50s} FAILED: {e}")

# 4. 试试 GitHub 上的开源数据
print()
print("=" * 60)
print("  4. GitHub 开源数据仓库")
print("=" * 60)
github_repos = [
    ("linshibo1994/dlt", "https://api.github.com/repos/linshibo1994/dlt"),
    ("kysae/dlt", "https://api.github.com/repos/kysae/dlt"),
]
for name, url in github_repos:
    try:
        r = requests.get(url, headers={**headers, "Accept": "application/vnd.github+json"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  {name}: stars={data.get('stargazers_count')}, description={data.get('description', '')[:80]}")
        else:
            print(f"  {name}: HTTP {r.status_code}")
    except Exception as e:
        print(f"  {name}: FAILED {e}")

# 5. raw.githubusercontent.com 直接抓数据
print()
print("=" * 60)
print("  5. raw.githubusercontent.com 数据文件")
print("=" * 60)
data_urls = [
    "https://raw.githubusercontent.com/linshibo1994/dlt/main/data/dlt_history.csv",
    "https://raw.githubusercontent.com/linshibo1994/dlt/master/data/dlt_history.csv",
    "https://raw.githubusercontent.com/linshibo1994/dlt/main/data/history.csv",
    "https://raw.githubusercontent.com/linshibo1994/dlt/main/dlt_history.json",
]
for u in data_urls:
    try:
        r = requests.get(u, headers=headers, timeout=10, allow_redirects=True)
        print(f"  {u[-60:]:60s} HTTP {r.status_code} len={len(r.text)} ctype={r.headers.get('Content-Type', '')[:30]}")
        if r.status_code == 200 and len(r.text) > 100:
            print(f"    First 200 chars: {r.text[:200]}")
    except Exception as e:
        print(f"  {u[-60:]:60s} FAILED: {e}")

# 6. 备用：易彩 8 选 1
print()
print("=" * 60)
print("  6. 备用站点")
print("=" * 60)
extras = [
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=dlt&issueStart=24001&issueEnd=24001&pageNo=1&pageSize=1",
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findKjxx/forIssue?name=dlt&code=24001",
    "https://www.9188.com/kaijiang/dlt/",
    "https://www.zhcw.com/dlt/kjgg/index.shtml",
    "https://m.cp.360.cn/kaijiang/dlt",
]
for u in extras:
    try:
        r = requests.get(u, headers=headers, timeout=10)
        print(f"  {u[-50:]:50s} HTTP {r.status_code} len={len(r.text)}")
    except Exception as e:
        print(f"  {u[-50:]:50s} FAILED {type(e).__name__}")
