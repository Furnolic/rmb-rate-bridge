import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta

SAFE_URL = "https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do"
MAIN_PAGE = "https://www.safe.gov.cn/safe/rmbhlzjj/index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": MAIN_PAGE,
    "Origin": "https://www.safe.gov.cn",
    "Content-Type": "application/x-www-form-urlencoded",
}

# 外管局标价法（披露附注需注明）
# 直接标价法 = 100外币折人民币
DIRECT_QUOTE = ["美元", "欧元", "日元", "港元", "英镑", "澳元", "新西兰元",
                "新加坡元", "瑞士法郎", "加元", "澳门元"]
# 间接标价法 = 100人民币折外币
INDIRECT_QUOTE = ["林吉特", "卢布", "兰特", "韩元", "迪拉姆", "里亚尔", "福林",
                  "兹罗提", "丹麦克朗", "瑞典克朗", "挪威克朗", "里拉", "比索", "泰铢"]

# ISO 4217 币种代码映射（妙搭 exchange_rate 表需要 currencyCode 字段）
CURRENCY_CODE = {
    "美元":"USD","欧元":"EUR","日元":"JPY","港元":"HKD","英镑":"GBP",
    "澳元":"AUD","新西兰元":"NZD","新加坡元":"SGD","瑞士法郎":"CHF",
    "加元":"CAD","澳门元":"MOP",
    "林吉特":"MYR","卢布":"RUB","兰特":"ZAR","韩元":"KRW","迪拉姆":"AED",
    "里亚尔":"SAR","福林":"HUF","兹罗提":"PLN","丹麦克朗":"DKK",
    "瑞典克朗":"SEK","挪威克朗":"NOK","里拉":"TRY","比索":"PHP","泰铢":"THB",
}


def _to_float(s):
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def get_rates(start_date, end_date):
    """查询日期范围内的人民币中间价。
    返回 list: [{date, rates:{币种: 汇率}}, ...]，按日期降序（最新在前）。
    """
    data = {
        "startDate": start_date,
        "endDate": end_date,
        "projectName": "美元",  # 任意值，外管局固定返回全部币种
        "queryYN": "true",
    }
    r = requests.post(SAFE_URL, data=data, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    result = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not header or header[0] != "日期":
            continue
        currencies = header[1:]
        for tr in rows[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if not cells or cells[0] == "日期" or "没有查询到" in cells[0]:
                continue
            rates = {}
            for i, cur in enumerate(currencies):
                if i + 1 < len(cells):
                    rates[cur] = _to_float(cells[i + 1])
            result.append({"date": cells[0], "rates": rates})
        break
    return result


def latest_rate(currency="美元", days_back=15):
    """取最近一个交易日的某币种中间价。"""
    today = datetime.today()
    start = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    rows = get_rates(start, end)
    if not rows:
        return None
    latest = rows[0]  # 降序，第一条最新
    return {"date": latest["date"], "currency": currency,
            "rate": latest["rates"].get(currency)}


def rate_on(date_str, currency="美元", days_back=10):
    """取指定日期的中间价；若该日非交易日，返回最近的前一个交易日。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    start = (d - timedelta(days=days_back)).strftime("%Y-%m-%d")
    rows = get_rates(start, date_str)
    for row in rows:  # 降序
        if row["date"] <= date_str:
            return {"date": row["date"], "currency": currency,
                    "rate": row["rates"].get(currency),
                    "note": "目标日非交易日，已取最近前一交易日" if row["date"] != date_str else None}
    return None


def to_rows(date_str, rates_dict, period_label=None, is_period_end=True):
    """将汇率字典转成妙搭表友好的扁平行数组（含 ISO 币种代码 + 标价法单位）。"""
    rows = []
    for name, rate in (rates_dict or {}).items():
        if rate is None:
            continue
        unit = "100外币折人民币" if name in DIRECT_QUOTE else "100人民币折外币"
        rows.append({
            "currencyCode": CURRENCY_CODE.get(name, ""),
            "currencyName": name,
            "rate": rate,
            "rateUnit": unit,
            "date": date_str,
            "period": period_label or date_str[:7],
            "isPeriodEnd": is_period_end,
        })
    return rows


if __name__ == "__main__":
    out_path = "C:/Users/Thinkpad/WorkBuddy/2026-08-06-16-00-44/rmb-rate-bridge/rates_sample.json"

    # 1) 2026年6月全部交易日、全部币种
    month = get_rates("2026-06-01", "2026-06-30")

    # 2) 最近交易日美元中间价
    latest = latest_rate("美元")

    # 3) 指定日期（含非交易日回退演示：6/27周六→取6/26）
    on_date = rate_on("2026-06-27", "欧元")

    sample = {
        "source": "国家外汇管理局 safe.gov.cn 人民币汇率中间价",
        "quoting_convention": {
            "直接标价法_100外币折人民币": DIRECT_QUOTE,
            "间接标价法_100人民币折外币": INDIRECT_QUOTE,
        },
        "month_2026_06_count": len(month),
        "month_2026_06_first_3_days": month[:3],
        "latest_usd": latest,
        "eur_on_2026_06_27_with_fallback": on_date,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)

    print(json.dumps(sample, ensure_ascii=False, indent=2))
    print(f"\n[已保存样例到] {out_path}")
