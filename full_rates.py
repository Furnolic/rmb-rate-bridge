"""完整汇率模块：94种货币（25种中间价换算 + 69种美元交叉汇率），统一为 1外币=X人民币。
逻辑已通过用户手工计算 94/100 100% 校验。"""
import requests
import re
import io
import calendar
from datetime import datetime, timedelta
import pandas as pd
from bs4 import BeautifulSoup

# ===== 直接/间接标价法分类（按用户指定，已校验）=====
# 直接（10种）：100外币折人民币
DIRECT_QUOTE = ["美元", "欧元", "日元", "港元", "英镑",
                "澳元", "新西兰元", "新加坡元", "瑞士法郎", "加元"]
# 间接（15种）：100人民币折外币
INDIRECT_QUOTE = ["澳门元", "林吉特", "卢布", "兰特", "韩元", "迪拉姆",
                  "里亚尔", "福林", "兹罗提", "丹麦克朗", "瑞典克朗",
                  "挪威克朗", "里拉", "比索", "泰铢"]

# ISO 4217 币种代码
CURRENCY_CODE = {
    "美元": "USD", "欧元": "EUR", "日元": "JPY", "港元": "HKD", "英镑": "GBP",
    "澳元": "AUD", "新西兰元": "NZD", "新加坡元": "SGD", "瑞士法郎": "CHF",
    "加元": "CAD", "澳门元": "MOP",
    "林吉特": "MYR", "卢布": "RUB", "兰特": "ZAR", "韩元": "KRW", "迪拉姆": "AED",
    "里亚尔": "SAR", "福林": "HUF", "兹罗提": "PLN", "丹麦克朗": "DKK",
    "瑞典克朗": "SEK", "挪威克朗": "NOK", "里拉": "TRY", "比索": "MXN", "泰铢": "THB",
}

SAFE_HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.safe.gov.cn/"}
SAFE_Q = "https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do"
SAFE_S2_IDX = "https://www.safe.gov.cn/safe/gzhbdmyzslb/index.html"


def _to_float(s):
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_source1(date_str):
    """取目标日（非交易日回退到最近前一交易日）的25种货币原始中间价。返回 {currency: published_rate}"""
    rows = _query_range(date_str, date_str)
    if not rows:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        rows = _query_range((d - timedelta(days=10)).strftime("%Y-%m-%d"), date_str)
    return rows[0] if rows else None  # {date, rates}


def _query_range(start, end):
    r = requests.post(SAFE_Q, data={"startDate": start, "endDate": end,
                                   "projectName": "美元", "queryYN": "true"},
                     headers=SAFE_HDR, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [c.get_text(strip=True) for c in trs[0].find_all(["th", "td"])]
        if not header or header[0] != "日期":
            continue
        curs = header[1:]
        for tr in trs[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if not cells or cells[0] == "日期" or "没有查询到" in cells[0]:
                continue
            d = {"date": cells[0], "rates": {}}
            for i, cur in enumerate(curs):
                if i + 1 < len(cells):
                    d["rates"][cur] = _to_float(cells[i + 1])
            out.append(d)
        break
    return out  # 降序，最新在前


def _convert(name, pub):
    """Source 1 原始中间价 → 1外币=X人民币"""
    if pub is None:
        return None
    if name in DIRECT_QUOTE:
        return pub / 100.0      # 100外币=X人民币 → 1外币=X/100
    if name in INDIRECT_QUOTE:
        return 100.0 / pub      # 100人民币=X外币 → 1外币=100/X
    return None


def _fetch_source2_excel(date_str):
    """gzhbdmyzslb 索引页→详情页→Excel→解析。返回 {code: (中文名, 1外币=X美元)}"""
    ymd = date_str.replace("-", "")
    yyyy, mmdd = ymd[:4], ymd[4:]
    idx = requests.get(SAFE_S2_IDX, headers=SAFE_HDR, timeout=30).text
    entries = re.findall(r'href="(/safe/(\d{4})/(\d{4})/\d+\.html)"', idx)
    detail_url = None
    for href, y, md in entries:
        if y == yyyy and md == mmdd:
            detail_url = "https://www.safe.gov.cn" + href
            break
    if not detail_url and entries:
        detail_url = "https://www.safe.gov.cn" + entries[0][0]
    if not detail_url:
        return {}
    r = requests.get(detail_url, headers=SAFE_HDR, timeout=30)
    r.encoding = "utf-8"
    m = re.search(r'href="(/safe/file/file/[^"]+\.xlsx)"', r.text) or \
        re.search(r'href="(/safe/file/file/[^"]+\.xls)"', r.text)
    if not m:
        return {}
    fr = requests.get("https://www.safe.gov.cn" + m.group(1), headers=SAFE_HDR, timeout=60)
    try:
        df = pd.read_excel(io.BytesIO(fr.content), header=None, engine="openpyxl")
    except Exception:
        df = pd.read_excel(io.BytesIO(fr.content), header=None, engine="xlrd")
    records = {}
    for _, row in df.iterrows():
        for sc in [1, 5]:
            code = row.iloc[sc] if sc < len(row) else None
            rate = row.iloc[sc + 3] if sc + 3 < len(row) else None
            name_cn = row.iloc[sc + 1] if sc + 1 < len(row) else None
            if pd.isna(code) or pd.isna(rate):
                continue
            code = str(code).strip()
            try:
                rv = float(rate)
            except (ValueError, TypeError):
                continue
            if len(code) == 3 and code.isalpha():
                records[code] = (str(name_cn).strip() if not pd.isna(name_cn) else "", rv)
    return records


def full_rates_for_date(date_str):
    """完整94种：25种(Source1换算) + 其余(Source2交叉汇率)，统一 1外币=X人民币。"""
    s1 = _fetch_source1(date_str)
    if not s1:
        return None
    actual_date = s1["date"]
    rates_raw = s1["rates"]
    usd_pub = rates_raw.get("美元")
    if usd_pub is None:
        return None
    usd_to_cny = usd_pub / 100.0  # 1 USD = X CNY

    out = []
    source1_codes = set()
    for name in DIRECT_QUOTE + INDIRECT_QUOTE:
        pub = rates_raw.get(name)
        per_one = _convert(name, pub)
        if per_one is None:
            continue
        code = CURRENCY_CODE.get(name, "")
        source1_codes.add(code)
        out.append({
            "currencyCode": code,
            "currencyName": name,
            "rateRMB_per_1_foreign": round(per_one, 6),
            "originalPublished": pub,
            "originalUnit": "100外币折人民币" if name in DIRECT_QUOTE else "100人民币折外币",
            "source": "SAFE中间价(换算)",
        })

    # Source 2 交叉汇率：1外币 = (X美元) × (1美元=Y人民币)
    s2 = _fetch_source2_excel(actual_date)
    for code, (name_cn, per_usd) in s2.items():
        if code in source1_codes:
            continue
        out.append({
            "currencyCode": code,
            "currencyName": name_cn,
            "rateRMB_per_1_foreign": round(per_usd * usd_to_cny, 6),
            "originalPublished": per_usd,
            "originalUnit": "1外币折美元",
            "source": "SAFE美元折算表(交叉汇率)",
        })
    out.sort(key=lambda x: x["currencyCode"])
    return {
        "date": actual_date,
        "usd_to_cny": round(usd_to_cny, 6),
        "quoting_note": "直接标价法=100外币折人民币÷100；间接标价法=100÷(100人民币折外币)；交叉汇率=1外币折美元×美元兑人民币",
        "count": len(out),
        "rates": out,
    }


def full_rates_for_period(year, month):
    """某年月期末汇率：取该月最后一个汇率公布日。"""
    last_day = calendar.monthrange(year, month)[1]
    return full_rates_for_date(f"{year:04d}-{month:02d}-{last_day:02d}")


if __name__ == "__main__":
    import json
    r = full_rates_for_period(2026, 6)
    print(json.dumps({"date": r["date"], "usd_to_cny": r["usd_to_cny"],
                      "count": r["count"]}, ensure_ascii=False, indent=2))
    for x in r["rates"][:5]:
        print(" ", x["currencyCode"], x["currencyName"], x["rateRMB_per_1_foreign"], x["source"])
