"""
生成静态 JSON 文件到 docs/ 目录，供 GitHub Pages 托管。
飞书妙搭通过 https://Furnolic.github.io/rmb-rate-bridge/latest.json 直接读取，
无需服务器，无冷启动。

用法：python generate_static.py
"""

import json
import os
import sys
import calendar
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safe_rates import get_rates, latest_rate, rate_on, to_rows, CURRENCY_CODE, DIRECT_QUOTE, INDIRECT_QUOTE
from full_rates import full_rates_for_date

# 输出目录（GitHub Pages 从 docs/ 提供服务）
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
os.makedirs(OUT_DIR, exist_ok=True)

# 数据时间带时区说明
now_utc = datetime.utcnow()
now_cst = now_utc + timedelta(hours=8)
today_str = now_cst.strftime("%Y-%m-%d")

# 往前查 5 天以防今天非交易日
recent_rows = get_rates((now_cst - timedelta(days=5)).strftime("%Y-%m-%d"), today_str)

if not recent_rows:
    print("ERROR: 无法从外管局获取任何汇率数据")
    sys.exit(1)

latest_date = recent_rows[0]["date"]
latest_rates = recent_rows[0]["rates"]
usd_rate = latest_rates.get("美元")

print(f"最新交易日: {latest_date}")
print(f"美元中间价: {usd_rate}")

# ===== 1. latest.json — 最新交易日 25 种货币（扁平行格式，妙搭友好）=====
latest_rows = to_rows(latest_date, latest_rates, period_label=latest_date[:7], is_period_end=True)
latest_json = {
    "source": "国家外汇管理局 safe.gov.cn",
    "fetched_at_cst": now_cst.strftime("%Y-%m-%d %H:%M:%S"),
    "date": latest_date,
    "count": len(latest_rows),
    "data": latest_rows,
}
with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
    json.dump(latest_json, f, ensure_ascii=False, indent=2)
print(f"[OK] latest.json — {len(latest_rows)} 种货币")

# ===== 2. latest_full.json — 最新交易日 94 种货币（含交叉汇率）=====
full = full_rates_for_date(today_str)
if full:
    full["fetched_at_cst"] = now_cst.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(OUT_DIR, "latest_full.json"), "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)
    print(f"[OK] latest_full.json — {full['count']} 种货币（含交叉汇率）")
else:
    # 兜底：只输出 25 种
    print("[WARN] 交叉汇率抓取失败，latest_full.json 用 25 种兜底")
    with open(os.path.join(OUT_DIR, "latest_full.json"), "w", encoding="utf-8") as f:
        json.dump(latest_json, f, ensure_ascii=False, indent=2)

# ===== 3. usd.json — 仅美元汇率（轻量查询）=====
usd_json = {
    "source": "国家外汇管理局 safe.gov.cn",
    "fetched_at_cst": now_cst.strftime("%Y-%m-%d %H:%M:%S"),
    "date": latest_date,
    "currency": "美元",
    "currencyCode": "USD",
    "rate": usd_rate,
    "rateUnit": "100外币折人民币",
}
with open(os.path.join(OUT_DIR, "usd.json"), "w", encoding="utf-8") as f:
    json.dump(usd_json, f, ensure_ascii=False, indent=2)
print(f"[OK] usd.json — 美元中间价 {usd_rate}")

# ===== 4. health.json — 健康检查 / 状态页 =====
health = {
    "status": "ok",
    "service": "rmb-rate-bridge-static",
    "latest_date": latest_date,
    "fetched_at_cst": now_cst.strftime("%Y-%m-%d %H:%M:%S"),
    "files": ["latest.json", "latest_full.json", "usd.json", "health.json"],
}
with open(os.path.join(OUT_DIR, "health.json"), "w", encoding="utf-8") as f:
    json.dump(health, f, ensure_ascii=False, indent=2)
print(f"[OK] health.json")

# ===== 5. 首页 index.html — 状态展示 =====
index_html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>人民币中间价数据桥 · 静态版</title>
<style>body{{font-family:system-ui,Segoe UI,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#222;line-height:1.6}}h1{{font-size:21px}}code{{background:#f1f1f1;padding:2px 6px;border-radius:4px;font-size:13px}}.tag{{display:inline-block;background:#0F6E56;color:#fff;border-radius:4px;padding:1px 8px;font-size:12px}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{border:1px solid #ddd;padding:8px;text-align:left;font-size:14px}}th{{background:#f5f5f5}}a{{color:#0F6E56}}</style></head><body>
<h1>人民币中间价数据桥 <span class="tag">外管局 · 静态版</span></h1>
<p>数据由 GitHub Actions 每个工作日 10:00 (CST) 自动抓取，托管于 GitHub Pages。无冷启动，秒级响应。</p>
<table><tr><th>文件</th><th>内容</th><th>大小</th><th>链接</th></tr>
<tr><td>latest.json</td><td>最新交易日 25 种货币（妙搭扁平行格式）</td><td>25 条</td><td><a href="latest.json">latest.json</a></td></tr>
<tr><td>latest_full.json</td><td>最新交易日 94 种货币（含交叉汇率）</td><td>{full['count'] if full else '?'} 条</td><td><a href="latest_full.json">latest_full.json</a></td></tr>
<tr><td>usd.json</td><td>美元中间价（轻量）</td><td>1 条</td><td><a href="usd.json">usd.json</a></td></tr>
<tr><td>health.json</td><td>健康检查</td><td>-</td><td><a href="health.json">health.json</a></td></tr>
</table>
<p style="font-size:13px;color:#666">
最新交易日：{latest_date} · 美元中间价：{usd_rate}（100外币折人民币）<br>
数据来源：国家外汇管理局 safe.gov.cn · 抓取时间：{now_cst.strftime('%Y-%m-%d %H:%M:%S')} CST
</p>
</body></html>"""
with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(index_html)
print("[OK] index.html")

print(f"\n=== 静态文件已生成到 {OUT_DIR} ===")
print("GitHub Pages URL: https://Furnolic.github.io/rmb-rate-bridge/latest.json")
print("飞书妙搭自定义 API: https://Furnolic.github.io/rmb-rate-bridge/latest.json")