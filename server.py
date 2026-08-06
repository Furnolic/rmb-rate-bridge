from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import json
import sys
import os
import calendar
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safe_rates import get_rates, latest_rate, rate_on, to_rows
from full_rates import full_rates_for_date, full_rates_for_period


def period_end_rates(year, month):
    """取某年某月最后一个交易日的全部币种中间价（期末汇率）。"""
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    rows = get_rates(start, end)
    return rows[0] if rows else None  # 降序，第一条即月末最后交易日


def rates_on_with_fallback(date_str):
    """取指定日期全部币种；非交易日自动回退到最近前一交易日。"""
    rows = get_rates(date_str, date_str)
    if not rows:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        rows = get_rates((d - timedelta(days=10)).strftime("%Y-%m-%d"), date_str)
    if not rows:
        return None
    r = rows[0]
    note = "目标日非交易日，已取最近前一交易日" if r["date"] != date_str else None
    return {"date": r["date"], "rates": r["rates"], "note": note}


LANDING = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>人民币中间价数据桥</title>
<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#222;line-height:1.6}
h1{font-size:21px}code{background:#f1f1f1;padding:2px 6px;border-radius:4px;font-size:13px}
li{margin:8px 0}.tag{display:inline-block;background:#0F6E56;color:#fff;border-radius:4px;padding:1px 8px;font-size:12px}</style></head>
<body>
<h1>人民币中间价数据桥 <span class="tag">外管局</span></h1>
<p>本服务自动抓取国家外汇管理局(safe.gov.cn)人民币汇率中间价，供飞书妙搭"自定义API"调用，替代手工上传汇率。</p>
<h3>接口（均返回 JSON）</h3>
<ul>
<li><code>GET /rate?date=2026-06-30&currency=美元</code> — 指定日期某币种中间价（非交易日自动回退）</li>
<li><code>GET /rates?date=2026-06-30</code> — 指定日期全部 25 种货币中间价（期末汇率首选）</li>
<li><code>GET /period_end?year=2026&month=6</code> — 某月最后交易日全部中间价</li>
<li><code>GET /latest?currency=美元</code> — 最近交易日某币种中间价</li>
<li><code>GET /rates?start=2026-06-01&end=2026-06-30</code> — 日期区间全部数据</li>
<li><code>GET /health</code> — 健康检查</li>
</ul>
<p style="color:#666;font-size:13px">数据来源：国家外汇管理局。直接标价法=100外币折人民币；间接标价法=100人民币折外币。</p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        qs = parse_qs(p.query)
        path = p.path.rstrip("/") or "/"
        try:
            if path == "/health":
                return self._json(200, {"status": "ok", "service": "rmb-rate-bridge"})
            if path == "/":
                return self._html(LANDING)
            if path == "/rate":
                date = qs.get("date", [None])[0]
                cur = qs.get("currency", ["美元"])[0]
                if not date:
                    return self._json(400, {"error": "missing param: date"})
                return self._json(200, rate_on(date, cur) or {"error": "no data", "date": date})
            if path == "/rates":
                if "date" in qs:
                    r = rates_on_with_fallback(qs["date"][0])
                    return self._json(200, r or {"error": "no data", "date": qs["date"][0]})
                if "start" in qs and "end" in qs:
                    rows = get_rates(qs["start"][0], qs["end"][0])
                    return self._json(200, {"count": len(rows), "data": rows})
                return self._json(400, {"error": "use ?date= or ?start=&end="})
            if path == "/period_end":
                year = int(qs.get("year", [str(datetime.today().year)])[0])
                month = int(qs.get("month", [str(datetime.today().month)])[0])
                r = period_end_rates(year, month)
                if not r:
                    return self._json(200, {"error": "no data", "year": year, "month": month})
                return self._json(200, {"year": year, "month": month,
                                        "date": r["date"], "rates": r["rates"]})
            if path == "/sync":
                # 完整94种：25种(Source1换算) + 69种(Source2交叉汇率)，统一 1外币=X人民币
                if "date" in qs:
                    r = full_rates_for_date(qs["date"][0])
                    if not r:
                        return self._json(200, {"error": "no data", "date": qs["date"][0]})
                    return self._json(200, {"source": "国家外汇管理局 safe.gov.cn",
                                            "date": r["date"], "usd_to_cny": r["usd_to_cny"],
                                            "quoting_note": r["quoting_note"],
                                            "count": r["count"], "rates": r["rates"]})
                if "year" in qs:
                    y = int(qs["year"][0])
                    m = int(qs.get("month", [str(datetime.today().month)])[0])
                    r = full_rates_for_period(y, m)
                    if not r:
                        return self._json(200, {"error": "no data", "year": y, "month": m})
                    return self._json(200, {"source": "国家外汇管理局 safe.gov.cn",
                                            "year": y, "month": m, "period_end_date": r["date"],
                                            "usd_to_cny": r["usd_to_cny"],
                                            "quoting_note": r["quoting_note"],
                                            "count": r["count"], "rates": r["rates"]})
                return self._json(400, {"error": "use ?year=&month= or ?date="})
            if path == "/latest":
                cur = qs.get("currency", ["美元"])[0]
                return self._json(200, latest_rate(cur) or {"error": "no data"})
            return self._json(404, {"error": "not found", "path": path})
        except Exception as e:
            return self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"rmb-rate-bridge serving on http://0.0.0.0:{port}")
    srv.serve_forever()
