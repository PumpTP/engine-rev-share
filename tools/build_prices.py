"""Builds prices.json: national average pump prices per litre, in local currency.

Sources (free, open):
- EU Weekly Oil Bulletin (European Commission, CC BY 4.0): Euro-super 95 + diesel, 27 EU countries, EUR per 1000 L.
  Non-euro countries converted with ECB reference rates.
- US EIA weekly retail prices (public domain): regular gasoline + No 2 diesel, USD per gallon.
- UK DESNZ weekly road fuel prices (Open Government Licence): ULSP + ULSD, pence per litre.
Each source is optional: a failure keeps that country's last good values from the old prices.json.
Run: python tools/build_prices.py [out=prices.json]
"""
import csv, io, json, re, sys, datetime, urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "EngineRev price builder (+https://pumptp.github.io/engine-rev-share/)"}
GAL_L = 3.785411784

EU = {
    "Austria": ("AT", "EUR"), "Belgium": ("BE", "EUR"), "Bulgaria": ("BG", "EUR"), "Croatia": ("HR", "EUR"),
    "Cyprus": ("CY", "EUR"), "Czechia": ("CZ", "CZK"), "Denmark": ("DK", "DKK"), "Estonia": ("EE", "EUR"),
    "Finland": ("FI", "EUR"), "France": ("FR", "EUR"), "Germany": ("DE", "EUR"), "Greece": ("GR", "EUR"),
    "Hungary": ("HU", "HUF"), "Ireland": ("IE", "EUR"), "Italy": ("IT", "EUR"), "Latvia": ("LV", "EUR"),
    "Lithuania": ("LT", "EUR"), "Luxembourg": ("LU", "EUR"), "Malta": ("MT", "EUR"), "Netherlands": ("NL", "EUR"),
    "Poland": ("PL", "PLN"), "Portugal": ("PT", "EUR"), "Romania": ("RO", "RON"), "Slovakia": ("SK", "EUR"),
    "Slovenia": ("SI", "EUR"), "Spain": ("ES", "EUR"), "Sweden": ("SE", "SEK"),
}
WOB_PAGE = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"
WOB_KNOWN = "https://energy.ec.europa.eu/document/download/264c2d0f-f161-4ea3-a777-78faae59bea0_en"
ECB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
EIA = {"petrol": "https://www.eia.gov/dnav/pet/hist_xls/EMM_EPMR_PTE_NUS_DPGw.xls",
       "diesel": "https://www.eia.gov/dnav/pet/hist_xls/EMD_EPD2D_PTE_NUS_DPGw.xls"}
UK_API = "https://www.gov.uk/api/content/government/statistical-data-sets/oil-and-petroleum-products-weekly-statistics"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def iso(d):
    return d.date().isoformat() if isinstance(d, datetime.datetime) else str(d)[:10]


def ecb_rates():
    root = ET.fromstring(get(ECB))
    return {c.get("currency"): float(c.get("rate")) for c in root.iter() if c.get("currency")}


def eu():
    import openpyxl
    urls = [WOB_KNOWN]
    try:
        page = get(WOB_PAGE).decode("utf-8", "replace")
        for m in re.finditer(r'href="([^"]*document/download/[^"]+)"', page):
            if "with%20Taxes" in m.group(1) or "with Taxes" in m.group(1):
                u = m.group(1).replace("&amp;", "&")
                urls.insert(0, u if u.startswith("http") else "https://energy.ec.europa.eu" + u)
    except Exception as e:
        print("EU page:", e)
    best = None
    for u in dict.fromkeys(urls):
        try:
            ws = openpyxl.load_workbook(io.BytesIO(get(u)), data_only=True).worksheets[0]
            rows = list(ws.iter_rows(values_only=True))
            date = next(r[0] for r in rows[:5] if isinstance(r[0], datetime.datetime))
            if best is None or date > best[0]:
                best = (date, rows)
        except Exception as e:
            print("EU file", u[:80], e)
    if best is None:
        return {}
    date, rows = best
    rates = ecb_rates()
    out = {}
    for r in rows:
        name = (r[0] or "").strip() if isinstance(r[0], str) else None
        if name not in EU or not isinstance(r[1], (int, float)):
            continue
        cc, cur = EU[name]
        k = 1.0 if cur == "EUR" else rates[cur]
        out[cc] = {"cur": cur, "petrol": round(r[1] / 1000 * k, 4),
                   "diesel": round(r[2] / 1000 * k, 4) if isinstance(r[2], (int, float)) else None,
                   "date": iso(date), "src": "EU Weekly Oil Bulletin"}
    print("EU", len(out), iso(date))
    return out


def us():
    import pandas as pd
    v = {}
    for k, u in EIA.items():
        df = pd.read_excel(io.BytesIO(get(u)), sheet_name="Data 1", skiprows=2).dropna()
        d, p = df.iloc[-1, 0], float(df.iloc[-1, 1])
        v[k], v["date"] = round(p / GAL_L, 4), iso(d)
    print("US", v)
    return {"US": {"cur": "USD", "petrol": v["petrol"], "diesel": v["diesel"], "date": v["date"], "src": "US EIA"}}


def uk():
    found = []
    for src in (UK_API, UK_API.replace("/api/content", "")):
        try:
            found += re.findall(r'https://assets\.publishing\.service\.gov\.uk/[^"\'\s<>\\]+?\.csv', get(src).decode("utf-8", "replace"))
        except Exception as e:
            print("UK", src, e)
    url = next(u for u in found if "2018" in u)
    text = get(url).decode("utf-8-sig", "replace")
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    hi = next(i for i, r in enumerate(rows) if any("ULSP" in c for c in r) and any("ULSD" in c for c in r))
    h = rows[hi]
    ip = next(i for i, c in enumerate(h) if "ULSP" in c and "price" in c.lower())
    idl = next(i for i, c in enumerate(h) if "ULSD" in c and "price" in c.lower())
    data = [r for r in rows[hi + 1:] if len(r) > max(ip, idl) and re.match(r"^\d", r[0]) and r[ip].strip()]
    last = data[-1]
    d = last[0]
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            d = datetime.datetime.strptime(last[0], f).date().isoformat(); break
        except ValueError:
            pass
    v = {"cur": "GBP", "petrol": round(float(last[ip]) / 100, 4), "diesel": round(float(last[idl]) / 100, 4),
         "date": d, "src": "UK DESNZ"}
    print("UK", h[ip], h[idl], v)
    return {"GB": v}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "prices.json"
    try:
        old = json.load(open(out_path)).get("countries", {})
    except Exception:
        old = {}
    countries = dict(old)
    for f in (eu, us, uk):
        try:
            countries.update(f())
        except Exception as e:
            print(f.__name__, "failed:", repr(e))
    if countries == old:
        print("no change")
        return
    doc = {"v": 1, "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "unit": "per litre, local currency", "countries": dict(sorted(countries.items())),
           "credits": "EU Weekly Oil Bulletin (European Commission, CC BY 4.0); US EIA; UK DESNZ (Open Government Licence v3.0)"}
    json.dump(doc, open(out_path, "w"), indent=1, ensure_ascii=False)
    print("wrote", len(countries), "countries")


if __name__ == "__main__":
    main()
