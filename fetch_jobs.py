"""每日抓取職缺 -> docs/jobs.json。需要環境變數 REED_KEY（免費申請 reed.co.uk/developers/jobseeker）。"""
import csv, io, json, os, re, time, datetime as dt
import requests

UA = {"User-Agent": "Mozilla/5.0 (job-radar personal use)"}
# 倫敦：只留大型、通常有 Skilled Worker sponsorship 的雇主（可自行增減）
LARGE = re.compile(r"deloitte|pwc|kpmg|ey\b|ernst|accenture|mckinsey|bcg|bain|oliver wyman|oc&c|lek|"
    r"baringa|pa consulting|fti|alvarez|jpmorgan|goldman|morgan stanley|barclays|hsbc|lloyds|natwest|"
    r"standard chartered|ubs|citi|bank of america|deutsche|bnp|blackrock|lseg|london stock exchange|"
    r"google|microsoft|amazon|meta|apple|nvidia|unilever|bp\b|shell|astrazeneca|gsk|vodafone|"
    r"aviva|legal & general|schroders|fidelity|wtw|willis|aon|marsh|nielsen|kantar|capgemini|ibm", re.I)
TW_BIG = re.compile(r"台積|聯發科|輝達|nvidia|google|微軟|microsoft|amazon|亞馬遜|美光|micron|蝦皮|shopee|sea|"
    r"星展|dbs|花旗|citi|匯豐|hsbc|摩根|jpmorgan|渣打|安永|勤業|deloitte|資誠|pwc|KPMG|安侯|寶僑|聯合利華|"
    r"台達|鴻海|廣達|緯創|華碩|友達|日月光|高通|qualcomm|英特爾|intel|AMD|思科|cisco|sap|oracle|甲骨文", re.I)


GOV_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
_STOP = re.compile(r"\b(limited|ltd|plc|llp|llc|inc|uk|u\.k\.|group|holdings|the|international|services|\(uk\))\b|[^a-z0-9 ]")

def norm(n):
    return re.sub(r"\s+", " ", _STOP.sub(" ", n.lower())).strip()

def load_sponsors():
    """下載英國內政部 Skilled Worker 持牌雇主名單，回傳正規化後的名稱集合。"""
    try:
        html = requests.get(GOV_PAGE, headers=UA, timeout=30).text
        link = re.search(r"https://assets\.publishing\.service\.gov\.uk/[^\"' ]+\.csv", html).group(0)
        raw = requests.get(link, headers=UA, timeout=120).content.decode("utf-8-sig", "replace")
        names = set()
        for row in csv.DictReader(io.StringIO(raw)):
            if "skilled worker" in (row.get("Route") or "").lower() and (row.get("Type & Rating") or "").lower().startswith("worker"):
                names.add(norm(row["Organisation Name"]))
        print("sponsors:", len(names), link)
        return names
    except Exception as e:
        print("sponsor register fail", e)
        return set()

def is_sponsor(company, names):
    c = norm(company)
    if not c or not names:
        return None  # 無法判斷
    return any(n == c or n.startswith(c + " ") for n in names)

def tw_104(keyword):
    url = "https://www.104.com.tw/jobs/search/list"
    p = dict(ro=0, kwop=7, keyword=keyword, area="6001001000", order=15, asc=0, page=1, mode="s", jobsource="index_s")
    h = {**UA, "Referer": "https://www.104.com.tw/jobs/search/"}
    out = []
    for page in (1, 2, 3):
        p["page"] = page
        try:
            r = requests.get(url, params=p, headers=h, timeout=20).json()
            for j in r["data"]["list"]:
                lo, hi = int(j.get("salaryLow") or 0), int(j.get("salaryHigh") or 0)
                if not TW_BIG.search(j["custName"]) or hi < 70000:  # 月薪≥7萬
                    continue
                out.append(dict(region="tw", title=j["jobName"], company=j["custName"],
                    loc=j.get("jobAddrNoDesc", ""), annual=hi * 12, pay=f"月薪 {lo:,}–{hi:,}（×12≈{hi*12/1e4:.0f}萬，未含年終）",
                    url=j["link"]["job"], date=str(j.get("appearDate", "")), kw=keyword))
        except Exception as e:
            print("104 fail", keyword, page, e)
        time.sleep(1.5)
    return out

def uk_reed(what, kind):
    """Reed 官方 Jobseeker API（免費金鑰）。認證方式：金鑰當 Basic Auth 帳號，密碼留空。"""
    key = os.getenv("REED_KEY")
    if not key:
        print("no reed key"); return []
    out = []
    try:
        r = requests.get("https://www.reed.co.uk/api/1.0/search", auth=(key, ""), timeout=30, params={
            "keywords": what, "locationName": "London", "distanceFromLocation": 15,
            "resultsToTake": 100, "permanent": "true", **({"graduate": "true"} if kind == "grad" else {})}).json()
        for j in r.get("results", []):
            c = j.get("employerName", "")
            if not LARGE.search(c): continue
            lo, hi = int(j.get("minimumSalary") or 0), int(j.get("maximumSalary") or 0)
            try:
                d = dt.datetime.strptime(j.get("date", ""), "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                d = str(j.get("date", ""))
            out.append(dict(region="uk", kind=kind, title=j["jobTitle"], company=c, loc=j.get("locationName", ""),
                annual=hi, pay=f"£{lo:,}–£{hi:,}" if hi else "未公布", url=j["jobUrl"], date=d))
    except Exception as e:
        print("reed fail", what, e)
    time.sleep(1)
    return out

CURATED = [  # 有明確截止日的 graduate program，手動維護
 dict(region="uk", title="Lloyds — Data Science & AI Graduate Scheme", dl="2026-11-29", url="https://www.brightnetwork.co.uk/graduate-career-advice/choosing-a-career/application-deadlines-graduate-schemes/"),
 dict(region="uk", title="EY-Parthenon Graduate (Sep 2027)", dl="rolling", url="https://www.gradcracker.com/hub/615/ey/graduate-job/84988/ey-parthenon-graduate-programmes-september-2027-intake"),
 dict(region="uk", title="Monitor Deloitte Graduate（只收學生簽證身分，已用過 Graduate 簽證者不可，需在 LBS 在學期間申請）", dl="rolling", url="https://www.gradcracker.com/hub/301/deloitte/graduate-job/86138/graduate-monitor-deloitte"),
 dict(region="uk", title="Accenture AI & Data Graduate 2027–28", dl="rolling", url="https://www.gradcracker.com/hub/269/accenture/graduate-job/85142/london-ai-and-data-graduate-programme-2027-2028"),
 dict(region="tw", title="Sea Global MAP（年薪200萬起）— 今年已截止，預期2027年8月開下一輪", dl="2026-10-31", url="https://udn.com/news/story/7241/9732954"),
 dict(region="tw", title="星展儲備幹部 — 今年已截止，預期2027年9月開下一屆", dl="2026-11-08", url="https://udn.com/news/story/7239/9747053"),
]

def main():
    jobs = []
    sponsors = load_sponsors()
    for kw in ["data analyst", "business analyst", "management associate", "儲備幹部", "商業分析", "product analyst"]:
        jobs += tw_104(kw)
    for what, kind in [("graduate analyst", "grad"), ("graduate data", "grad"), ("associate analytics", "assoc"),
                       ("graduate consultant", "grad"), ("associate consultant", "assoc")]:
        jobs += uk_reed(what, kind)
    for j in jobs:
        if j["region"] == "uk":
            j["sponsor"] = is_sponsor(j["company"], sponsors)
    seen, uniq = set(), []
    for j in sorted(jobs, key=lambda x: -x["annual"]):
        key = (j["company"], j["title"])
        if key not in seen:
            seen.add(key); uniq.append(j)
    json.dump(dict(updated=dt.datetime.utcnow().isoformat() + "Z", jobs=uniq, curated=CURATED),
              open("docs/jobs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(uniq), "jobs")

if __name__ == "__main__":
    main()
