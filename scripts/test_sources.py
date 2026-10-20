import os
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ.pop(k, None)

import requests
import re

r = requests.get('https://lottery.sina.com.cn/', timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
print('Status:', r.status_code, 'Len:', len(r.text))

# 找大乐透相关链接
for pat in ['dlt', 'zs', 'dltHistory', 'history']:
    links = re.findall(r'href="([^"]*' + pat + r'[^"]*?)"', r.text, re.IGNORECASE)
    print(f'{pat} links ({len(links)}):', links[:5])
