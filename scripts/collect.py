#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trend Dashboard - 데이터 수집기

원본 사이트(easyautomation.co.kr/trend)와 동일한 계열의 공개 소스에서 직접 수집한다.
  1) Google Trends 급상승 검색어 (RSS, 무인증)
  2) 경제/주요 뉴스 (언론사 + Google News RSS, 무인증)
  3) 시장지표 (Yahoo Finance / Upbit / exchangerate, 무인증)
  4) 부동산 실거래 (공공데이터포털 국토교통부 API, 서비스키 필요 - 없으면 생략)

설계 원칙: 어떤 소스가 죽어도 전체 수집이 실패하지 않는다.
실패한 소스는 payload["sources"] 에 상태만 기록되고 나머지는 정상 갱신된다.
"""

import concurrent.futures
import json
import os
import re
import sys
import time
import html
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# Windows self-hosted 러너의 콘솔 인코딩이 UTF-8이 아니면 한글 print()가 GitHub Actions 로그에서 깨진다
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

HISTORY_DAYS = 30
TIMEOUT = 20

# 부동산 조회 지역 (법정동 코드 5자리). 원하는 지역으로 바꾸면 된다.
REGION_CODES = {
    # ── 서울특별시 25개 자치구 ──
    "11110": "서울 종로구", "11140": "서울 중구", "11170": "서울 용산구",
    "11200": "서울 성동구", "11215": "서울 광진구", "11230": "서울 동대문구",
    "11260": "서울 중랑구", "11290": "서울 성북구", "11305": "서울 강북구",
    "11320": "서울 도봉구", "11350": "서울 노원구", "11380": "서울 은평구",
    "11410": "서울 서대문구", "11440": "서울 마포구", "11470": "서울 양천구",
    "11500": "서울 강서구", "11530": "서울 구로구", "11545": "서울 금천구",
    "11560": "서울 영등포구", "11590": "서울 동작구", "11620": "서울 관악구",
    "11650": "서울 서초구", "11680": "서울 강남구", "11710": "서울 송파구",
    "11740": "서울 강동구",
    # ── 경기도 ──
    "41111": "수원 장안구", "41113": "수원 권선구", "41115": "수원 팔달구",
    "41117": "수원 영통구",
    "41131": "성남 수정구", "41133": "성남 중원구", "41135": "성남 분당구",
    "41150": "의정부시",
    "41171": "안양 만안구", "41173": "안양 동안구",
    "41190": "부천시", "41210": "광명시", "41220": "평택시", "41250": "동두천시",
    "41271": "안산 상록구", "41273": "안산 단원구",
    "41281": "고양 덕양구", "41285": "고양 일산동구", "41287": "고양 일산서구",
    "41290": "과천시", "41310": "구리시", "41360": "남양주시", "41370": "오산시",
    "41390": "시흥시", "41410": "군포시", "41430": "의왕시", "41450": "하남시",
    "41461": "용인 처인구", "41463": "용인 기흥구", "41465": "용인 수지구",
    "41480": "파주시", "41500": "이천시", "41550": "안성시", "41570": "김포시",
    "41590": "화성시", "41610": "광주시", "41630": "양주시", "41650": "포천시",
    "41670": "여주시", "41800": "연천군", "41820": "가평군", "41830": "양평군",
}

NEWS_FEEDS = [
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("연합뉴스 최신", "https://www.yna.co.kr/rss/news.xml"),
    ("한국경제", "https://rss.hankyung.com/feed/economy.xml"),
    ("매일경제 경제", "https://www.mk.co.kr/rss/30100041/"),
    ("SBS 경제", "https://news.sbs.co.kr/news/ReplayRssFeed.do?prog_cd=R1&plink=RSSREADER"),
    ("Google News 비즈니스",
     "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko"),
    ("Google News 헤드라인",
     "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"),
]

MARKET_TICKERS = [
    ("코스피", "^KS11", "pt"),
    ("코스닥", "^KQ11", "pt"),
    ("원/달러", "KRW=X", "원"),
    ("S&P 500", "^GSPC", "pt"),
    ("나스닥", "^IXIC", "pt"),
    ("WTI 유가", "CL=F", "$"),
    ("금", "GC=F", "$"),
]

# 뉴스 키워드 추출에서 제외할 흔한 단어
STOPWORDS = set("""
기자 뉴스 속보 단독 종합 사진 영상 오늘 어제 내일 올해 작년 지난해 이번 관련 대한 위해 통해 대해
그러나 하지만 있다 없다 한다 된다 이다 라며 라고 밝혔다 전했다 나섰다 이날 지난 최근 상황 경우
가운데 대비 기준 대표 회장 사장 정부 국내 해외 전년 동기 억원 조원 만원 포인트 이상 이하 상승 하락
연합뉴스 한국경제 매일경제 뉴시스 머니투데이 서울경제 파이낸셜 이데일리 아시아경제 데일리 미디어
""".split())


# ----------------------------------------------------------------------------
# 공통 유틸
# ----------------------------------------------------------------------------

def fetch(url, timeout=TIMEOUT, retries=2):
    """URL을 가져와 bytes 반환. 실패 시 예외."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


def strip_tags(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_pubdate(text):
    """RSS pubDate → KST datetime. 실패하면 None."""
    if not text:
        return None
    text = text.strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(text, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST)
        except ValueError:
            continue
    return None


def tokenize_ko(text):
    """한글/영문 토큰 추출 (형태소 분석기 없이 가볍게)."""
    text = re.sub(r"[^\w가-힣 ]", " ", text)
    out = []
    for w in text.split():
        if len(w) < 2 or len(w) > 12:
            continue
        if w in STOPWORDS:
            continue
        if w.isdigit():
            continue
        # 조사 꼬리 다듬기
        w = re.sub(r"(은|는|이|가|을|를|의|에|와|과|도|로|으로|에서|까지|부터)$", "", w)
        if len(w) < 2 or w in STOPWORDS:
            continue
        out.append(w)
    return out


# ----------------------------------------------------------------------------
# 1) Google Trends 급상승 검색어
# ----------------------------------------------------------------------------

HT_NS = "{https://trends.google.com/trending/rss}"


def collect_google_trends(geo="KR"):
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    raw = fetch(url)
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        traffic = (it.findtext(HT_NS + "approx_traffic") or "").strip()
        pub = parse_pubdate(it.findtext("pubDate"))
        picture = (it.findtext(HT_NS + "picture") or "").strip()
        if picture.startswith("//"):
            picture = "https:" + picture

        news = []
        for ni in it.findall(HT_NS + "news_item"):
            news.append({
                "title": strip_tags(ni.findtext(HT_NS + "news_item_title")),
                "url": (ni.findtext(HT_NS + "news_item_url") or "").strip(),
                "source": strip_tags(ni.findtext(HT_NS + "news_item_source")),
            })

        items.append({
            "keyword": title,
            "traffic": traffic or "-",
            "traffic_num": int(re.sub(r"[^\d]", "", traffic) or 0),
            "started_at": pub.isoformat() if pub else None,
            "picture": picture,
            "news": news[:3],
        })

    items.sort(key=lambda x: x["traffic_num"], reverse=True)
    return items


# ----------------------------------------------------------------------------
# 2) 경제/주요 뉴스
# ----------------------------------------------------------------------------

def collect_news():
    articles = []
    feed_status = []
    for name, url in NEWS_FEEDS:
        try:
            raw = fetch(url, timeout=15, retries=1)
            root = ET.fromstring(raw)
            n = 0
            for it in root.iter("item"):
                title = strip_tags(it.findtext("title"))
                link = (it.findtext("link") or "").strip()
                if not title or not link:
                    continue
                pub = parse_pubdate(it.findtext("pubDate"))
                desc = strip_tags(it.findtext("description"))[:220]
                articles.append({
                    "title": title,
                    "url": link,
                    "source": name,
                    "summary": desc,
                    "published_at": pub.isoformat() if pub else None,
                    "_ts": pub.timestamp() if pub else 0,
                })
                n += 1
                if n >= 40:
                    break
            feed_status.append({"feed": name, "ok": True, "count": n})
        except Exception as e:  # noqa: BLE001
            feed_status.append({"feed": name, "ok": False, "error": str(e)[:120]})

    # 제목 기준 중복 제거
    seen, deduped = set(), []
    for a in sorted(articles, key=lambda x: x["_ts"], reverse=True):
        key = re.sub(r"[^\w가-힣]", "", a["title"])[:28]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)

    return deduped, feed_status


def build_timeline(articles):
    """시간대(KST 시각)별 기사 묶음."""
    buckets = defaultdict(list)
    now = datetime.now(KST)
    for a in articles:
        if not a["published_at"]:
            continue
        dt = datetime.fromisoformat(a["published_at"])
        if (now - dt) > timedelta(hours=24):
            continue
        buckets[dt.hour].append({
            "title": a["title"], "url": a["url"],
            "source": a["source"], "time": dt.strftime("%H:%M"),
        })
    return [{"hour": h, "items": buckets[h][:8], "count": len(buckets[h])}
            for h in sorted(buckets.keys(), reverse=True)]


def build_clusters(articles, top_n=8):
    """제목 토큰 빈도로 '지금 화제인 이슈' 클러스터를 만든다."""
    counter = Counter()
    for a in articles[:180]:
        counter.update(set(tokenize_ko(a["title"])))

    clusters = []
    used_titles = set()
    for token, cnt in counter.most_common(60):
        if cnt < 3:
            break
        members = [a for a in articles
                   if token in a["title"] and a["title"] not in used_titles]
        if len(members) < 3:
            continue
        for m in members[:5]:
            used_titles.add(m["title"])
        clusters.append({
            "topic": token,
            "count": cnt,
            "articles": [{"title": m["title"], "url": m["url"], "source": m["source"]}
                         for m in members[:5]],
        })
        if len(clusters) >= top_n:
            break
    return clusters


# ----------------------------------------------------------------------------
# 3) 시장지표
# ----------------------------------------------------------------------------

def yahoo_quote(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol)
           + "?range=5d&interval=1d")
    data = json.loads(fetch(url, timeout=15, retries=1).decode("utf-8"))
    meta = data["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        raise ValueError("no price")
    change = (price - prev) if prev else 0.0
    rate = (change / prev * 100) if prev else 0.0
    return {"price": round(price, 2), "change": round(change, 2), "rate": round(rate, 2)}


def upbit_btc():
    data = json.loads(fetch("https://api.upbit.com/v1/ticker?markets=KRW-BTC",
                            timeout=15, retries=1).decode("utf-8"))[0]
    return {
        "price": round(data["trade_price"]),
        "change": round(data["signed_change_price"]),
        "rate": round(data["signed_change_rate"] * 100, 2),
    }


def fx_fallback():
    data = json.loads(fetch("https://open.er-api.com/v6/latest/USD",
                            timeout=15, retries=1).decode("utf-8"))
    krw = data["rates"]["KRW"]
    return {"price": round(krw, 2), "change": 0.0, "rate": 0.0}


def collect_market():
    out, errors = [], []
    for label, symbol, unit in MARKET_TICKERS:
        try:
            q = yahoo_quote(symbol)
            out.append({"label": label, "unit": unit, **q})
        except Exception as e:  # noqa: BLE001
            if symbol == "KRW=X":
                try:
                    out.append({"label": label, "unit": unit, **fx_fallback()})
                    continue
                except Exception:  # noqa: BLE001
                    pass
            errors.append(f"{label}: {str(e)[:80]}")

    try:
        out.append({"label": "비트코인", "unit": "원", **upbit_btc()})
    except Exception as e:  # noqa: BLE001
        errors.append(f"비트코인: {str(e)[:80]}")

    return out, errors


# ----------------------------------------------------------------------------
# 4) 부동산 실거래 (공공데이터포털)
# ----------------------------------------------------------------------------

RE_PATH = "1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

# GitHub Actions 러너에서 data.go.kr 로의 TLS 핸드셰이크가 막히는 경우가 있어
# https → http 순으로 시도한다. 처음 성공한 스킴을 이후 지역에도 재사용.
RE_BASES = [
    f"https://apis.data.go.kr/{RE_PATH}",
    f"http://apis.data.go.kr/{RE_PATH}",
]
_re_base_ok = None


def re_fetch(qs):
    """부동산 API 호출. 동작하는 스킴을 찾아 기억한다."""
    global _re_base_ok
    bases = [_re_base_ok] if _re_base_ok else RE_BASES
    last = None
    for base in bases:
        try:
            raw = fetch(f"{base}?{qs}", timeout=12, retries=0)
            if _re_base_ok is None:
                _re_base_ok = base
                print(f"        (연결 성공 스킴: {base.split(':')[0]})")
            return raw
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def _re_query(service_key, code, ym):
    return urllib.parse.urlencode({
        "serviceKey": service_key,
        "LAWD_CD": code,
        "DEAL_YMD": ym,
        "numOfRows": "300",
        "pageNo": "1",
    }, safe="%")


def _re_parse(raw, code, name):
    """XML 응답 → 지역 요약. API 에러면 error 키를 담아 돌려준다."""
    root = ET.fromstring(raw)

    # 공공데이터포털은 에러도 HTTP 200 + XML 본문으로 돌려준다
    msg = root.findtext(".//returnAuthMsg") or ""
    code_msg = root.findtext(".//resultMsg") or root.findtext(".//errMsg") or ""
    result_code = (root.findtext(".//resultCode") or "").strip()
    if msg or (result_code and result_code not in ("00", "0")):
        detail = (msg or code_msg or f"resultCode={result_code}").strip()
        return {"code": code, "name": name, "count": 0, "error": f"[rc={result_code}] {detail}"[:150]}

    deals = []
    for item in root.iter("item"):
        def g(tag):
            v = item.findtext(tag)
            return v.strip() if v else ""
        amount = re.sub(r"[^\d]", "", g("dealAmount"))
        if not amount:
            continue
        area = g("excluUseAr")
        deals.append({
            "apt": g("aptNm") or g("aptName"),
            "dong": g("umdNm"),
            "amount": int(amount),                    # 만원
            "area": float(area) if area else 0.0,     # ㎡
            "floor": g("floor"),
            "day": g("dealDay"),
        })

    if not deals:
        return {"code": code, "name": name, "count": 0}

    amounts = [d["amount"] for d in deals]
    return {
        "code": code,
        "name": name,
        "count": len(deals),
        "avg_amount": round(sum(amounts) / len(amounts)),
        "max_deal": max(deals, key=lambda d: d["amount"]),
        "recent": sorted(deals, key=lambda d: d["day"], reverse=True)[:5],
    }


def collect_realestate(service_key):
    """국토교통부 아파트 매매 실거래가 (서울 전역 + 경기 전역).

    지역이 많으므로 병렬로 가져온다. 다만 data.go.kr 은 해외 IP를 막는 일이
    있어서, 먼저 한 지역으로 연결을 확인(probe)하고 실패하면 즉시 접는다.
    수십 개 지역의 타임아웃을 기다리며 몇 분을 버리지 않기 위해서다.
    """
    if not service_key:
        return None, ["서비스키 없음 (DATA_GO_KR_KEY 시크릿 미설정)"]

    ym = datetime.now(KST).strftime("%Y%m")
    items = list(REGION_CODES.items())

    # ── 1) 연결 확인 ──
    probe_code, probe_name = items[0]
    try:
        raw = re_fetch(_re_query(service_key, probe_code, ym))
    except Exception as e:  # noqa: BLE001
        note = (f"data.go.kr 연결 불가 ({str(e)[:50]}) — "
                f"실행 서버의 IP가 차단된 것으로 보임")
        print(f"        {note}")
        print(f"        {len(items)}개 지역 전부 건너뜀")
        return ({"month": ym, "regions": [], "region_count": 0,
                 "total_count": 0, "unreachable": True, "errors": [note]},
                [note])

    regions = [_re_parse(raw, probe_code, probe_name)]
    if regions[0].get("error"):
        print(f"        [디버그] 원본 응답: {raw[:300]}")

    # ── 2) 나머지 지역 병렬 수집 ──
    def one(pair):
        code, name = pair
        try:
            return _re_parse(re_fetch(_re_query(service_key, code, ym)), code, name)
        except Exception as e:  # noqa: BLE001
            return {"code": code, "name": name, "count": 0, "error": str(e)[:100]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        regions.extend(pool.map(one, items[1:]))

    errors = [f"{r['name']}: {r['error']}" for r in regions if r.get("error")]
    total = sum(r["count"] for r in regions)
    with_deals = [r for r in regions if r["count"]]
    with_deals.sort(key=lambda r: r["count"], reverse=True)

    print(f"        거래 있는 지역 {len(with_deals)}개 / 조회 {len(regions)}개"
          f" · 총 {total}건" + (f" · 실패 {len(errors)}개" if errors else ""))
    for r in with_deals[:5]:
        print(f"          {r['name']}: {r['count']}건")

    avg = (round(sum(r["avg_amount"] * r["count"] for r in with_deals) / total)
           if total else 0)

    return ({
        "month": ym,
        "regions": with_deals[:15],       # 표시용 상위 15개 지역
        "region_count": len(regions),
        "active_count": len(with_deals),
        "total_count": total,
        "avg_amount": avg,
        "unreachable": False,
        "errors": errors[:10],
    }, errors)


# ----------------------------------------------------------------------------
# 가공: 트렌드 × 뉴스 교차 분석
# ----------------------------------------------------------------------------

def cross_analyze(trends, articles):
    """급상승 키워드가 뉴스에서 얼마나 다뤄지는지 → '뉴스 확산도'를 계산."""
    result = []
    for t in trends[:20]:
        kw = t["keyword"]
        parts = [p for p in re.split(r"\s+", kw) if len(p) >= 2]
        hits = []
        for a in articles:
            blob = a["title"] + " " + a["summary"]
            if kw in blob or (parts and all(p in blob for p in parts)):
                hits.append({"title": a["title"], "url": a["url"], "source": a["source"]})
        coverage = len(hits)
        if coverage == 0:
            status, note = "검색만", "검색은 급증했지만 기사 노출은 아직 적음 → 선행 신호"
        elif coverage <= 2:
            status, note = "확산 초기", "기사가 막 붙기 시작한 단계"
        else:
            status, note = "보도 확산", "이미 다수 매체가 다루는 중"
        result.append({
            "keyword": kw,
            "traffic": t["traffic"],
            "traffic_num": t["traffic_num"],
            "coverage": coverage,
            "status": status,
            "note": note,
            "articles": hits[:4],
        })
    return result


def build_brief(trends, articles, cross, market):
    """오늘의 시그널 브리프 - 한 화면 요약."""
    now = datetime.now(KST)
    fresh = []
    for t in trends:
        if not t["started_at"]:
            continue
        dt = datetime.fromisoformat(t["started_at"])
        if (now - dt) <= timedelta(hours=6):
            fresh.append(t["keyword"])

    leading = [c["keyword"] for c in cross if c["status"] == "검색만"][:5]
    movers = sorted([m for m in market if m.get("rate") is not None],
                    key=lambda m: abs(m["rate"]), reverse=True)[:3]

    return {
        "generated_at": now.isoformat(),
        "generated_label": now.strftime("%Y-%m-%d %H:%M KST"),
        "fresh_keywords": fresh[:8],
        "leading_signals": leading,
        "news_count_24h": sum(1 for a in articles
                              if a["published_at"]
                              and (now - datetime.fromisoformat(a["published_at"]))
                              <= timedelta(hours=24)),
        "trend_count": len(trends),
        "top_movers": [{"label": m["label"], "rate": m["rate"]} for m in movers],
    }


# ----------------------------------------------------------------------------
# 히스토리 (30일 롤링)
# ----------------------------------------------------------------------------

def update_history(previous, trends):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    history = (previous or {}).get("history", [])
    history = [h for h in history if h.get("date") != today]
    history.append({
        "date": today,
        "keywords": [{"k": t["keyword"], "t": t["traffic_num"]} for t in trends[:20]],
    })
    history.sort(key=lambda h: h["date"])
    history = history[-HISTORY_DAYS:]

    # 며칠 연속 등장했는지 (지속 관심 키워드)
    streak = Counter()
    for h in history[-7:]:
        for k in h["keywords"]:
            streak[k["k"]] += 1
    persistent = [{"keyword": k, "days": v}
                  for k, v in streak.most_common(10) if v >= 2]

    return history, persistent


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "data/latest.json"
    prev_path = os.environ.get("PREV_JSON", "")
    previous = None
    if prev_path and os.path.exists(prev_path):
        try:
            with open(prev_path, encoding="utf-8") as f:
                previous = json.load(f)
        except Exception:  # noqa: BLE001
            previous = None

    sources = {}

    print("[1/4] Google Trends…")
    try:
        trends = collect_google_trends("KR")
        sources["google_trends"] = {"ok": True, "count": len(trends)}
    except Exception as e:  # noqa: BLE001
        trends = (previous or {}).get("trends", [])
        sources["google_trends"] = {"ok": False, "error": str(e)[:150],
                                    "fallback": "이전 데이터 유지"}
    print(f"      → {len(trends)}건")

    print("[2/4] 뉴스…")
    try:
        articles, feed_status = collect_news()
        sources["news"] = {"ok": bool(articles), "count": len(articles),
                           "feeds": feed_status}
    except Exception as e:  # noqa: BLE001
        articles, feed_status = (previous or {}).get("news", []), []
        sources["news"] = {"ok": False, "error": str(e)[:150]}
    print(f"      → {len(articles)}건")

    print("[3/4] 시장지표…")
    market, market_err = collect_market()
    sources["market"] = {"ok": bool(market), "count": len(market),
                         "errors": market_err}
    print(f"      → {len(market)}건")

    print("[4/4] 부동산 실거래…")
    realestate, re_err = collect_realestate(os.environ.get("DATA_GO_KR_KEY", "").strip())
    # '키가 있다'가 아니라 '실제로 거래 데이터가 들어왔다'를 정상으로 본다
    re_total = sum(r.get("count", 0) for r in (realestate or {}).get("regions", []))
    sources["realestate"] = {"ok": re_total > 0, "count": re_total, "errors": re_err}
    if realestate is None:
        print("      → 생략 (서비스키 없음)")
    elif re_total:
        print(f"      → 총 {re_total}건")
    else:
        print("      → 데이터 없음 (키 활성화 대기 중이거나 이번 달 거래 없음)")
        if re_err:
            print(f"      → 원인 예시: {re_err[0]}")

    cross = cross_analyze(trends, articles)
    history, persistent = update_history(previous, trends)

    payload = {
        "version": 2,
        "generated_at": datetime.now(KST).isoformat(),
        "brief": build_brief(trends, articles, cross, market),
        "trends": trends,
        "news": [{k: v for k, v in a.items() if not k.startswith("_")}
                 for a in articles[:120]],
        "timeline": build_timeline(articles),
        "clusters": build_clusters(articles),
        "cross": cross,
        "market": market,
        "realestate": realestate,
        "history": history,
        "persistent": persistent,
        "sources": sources,
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(out_path)
    print(f"\n완료: {out_path} ({size:,} bytes)")

    ok_count = sum(1 for s in sources.values() if s.get("ok"))
    print(f"소스 상태: {ok_count}/{len(sources)} 정상")
    if ok_count == 0:
        print("모든 소스 실패", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
