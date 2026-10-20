import sqlite3
c = sqlite3.connect('data-raw/lottery.db')
n = c.execute("SELECT COUNT(*) FROM draws WHERE game='ssq'").fetchone()[0]
mn, mx = c.execute("SELECT MIN(period), MAX(period) FROM draws WHERE game='ssq'").fetchone()
print(f'ssq: {n} 期, {mn} - {mx}')

# 已有大乐透
n2 = c.execute("SELECT COUNT(*) FROM draws WHERE game='dlt'").fetchone()[0]
print(f'dlt: {n2} 期')
