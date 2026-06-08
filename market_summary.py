import urllib.request
import urllib.parse
import json
import re
import os
from datetime import datetime, timezone, timedelta

# -- GitHub Secrets --
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_KEY"]

KST = timezone(timedelta(hours=9))
today = datetime.now(KST)
weekday = today.weekday()

if weekday >= 5:
    print("주말이라 시황 없음.")
    exit(0)

date_str = today.strftime("%Y년 %m월 %d일")
weekday_kor = ["월", "화", "수", "목", "금", "토", "일"][weekday]


def fetch_quote(symbol):
    """캔들 종가 기준으로 가져옴."""
    for host in ["query1", "query2"]:
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            result = data.get("chart", {}).get("result")
            if not result:
                continue
            closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            valid = [c for c in closes if c is not None]
            if len(valid) < 2:
                continue
            price = valid[-1]
            prev  = valid[-2]
            chg = price - prev
            pct = chg / prev * 100
            return {"price": price, "chg": chg, "pct": pct}
        except Exception as e:
            print(f"[{symbol}] {host} 실패: {e}")
    return None


def arrow(pct):
    return "▲" if pct >= 0 else "▼"


def fmt_pct(pct):
    return f"{arrow(pct)} {abs(pct):.2f}%"


# ── 지수 ──
INDICES = {"S&P 500": "^GSPC", "나스닥": "^IXIC", "다우존스": "^DJI"}
index_q = {}
for name, sym in INDICES.items():
    q = fetch_quote(sym)
    index_q[name] = q
    if not q:
        print(f"[{name}] 조회 실패")

# ── 섹터 ──
SECTORS = {
    "XLK": "기술", "XLC": "커뮤니케이션", "XLY": "경기소비재",
    "XLP": "필수소비재", "XLV": "헬스케어", "XLF": "금융",
    "XLI": "산업재", "XLE": "에너지", "XLB": "소재",
    "XLRE": "부동산", "XLU": "유틸리티",
}

# 섹터별 주요 종목 (거래대금 상위)
SECTOR_STOCKS = {
    "XLK":  ["AAPL", "MSFT", "NVDA"],
    "XLC":  ["META", "GOOGL", "NFLX"],
    "XLY":  ["AMZN", "TSLA", "HD"],
    "XLP":  ["PG", "KO", "COST"],
    "XLV":  ["UNH", "JNJ", "LLY"],
    "XLF":  ["JPM", "BRK-B", "V"],
    "XLI":  ["GE", "CAT", "HON"],
    "XLE":  ["XOM", "CVX", "COP"],
    "XLB":  ["LIN", "APD", "ECL"],
    "XLRE": ["PLD", "AMT", "EQIX"],
    "XLU":  ["NEE", "DUK", "SO"],
}

sector_q = {}
for ticker, name in SECTORS.items():
    q = fetch_quote(ticker)
    if q:
        sector_q[ticker] = {"name": name, **q}
    else:
        print(f"[{ticker}] 조회 실패")

sorted_sectors = sorted(sector_q.items(), key=lambda x: x[1]["pct"], reverse=True)
top3 = sorted_sectors[:5]
bot3 = sorted_sectors[-3:]
focus_sectors = top3 + bot3

# ── 주요 종목 데이터 수집 ──
print("주요 종목 데이터 수집 중...")
stock_data = {}
for ticker, _ in focus_sectors:
    for sym in SECTOR_STOCKS.get(ticker, []):
        q = fetch_quote(sym)
        if q:
            stock_data[sym] = q

# ── 매크로 ──
MACRO = {"10년물 금리": "^TNX", "달러 인덱스": "DX-Y.NYB", "WTI 유가": "CL=F", "VIX": "^VIX"}
macro_q = {}
for name, sym in MACRO.items():
    q = fetch_quote(sym)
    macro_q[name] = q
    if not q:
        print(f"[{name}] 조회 실패")


def scrape_tg_channel(channel, limit=10):
    """텔레그램 공개 채널 최신 메시지 스크래핑."""
    url = f"https://t.me/s/{channel}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="ignore")
        msgs = re.findall(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )
        texts = []
        for m in msgs[-limit:]:
            text = re.sub(r'<[^>]+>', ' ', m)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 20:
                texts.append(text)
        return texts
    except Exception as e:
        print(f"텔레그램 스크래핑 실패 ({channel}): {e}")
        return []


def fetch_stock_news(symbol, limit=2):
    """Yahoo Finance 검색 API로 종목 최신 뉴스 헤드라인 수집."""
    url = (
        f"https://query1.finance.yahoo.com/v1/finance/search"
        f"?q={symbol}&newsCount={limit}&lang=en-US&region=US"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return [item["title"] for item in data.get("news", []) if item.get("title")]
    except Exception as e:
        print(f"[{symbol}] 뉴스 실패: {e}")
        return []


def call_gemini(prompt):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8000}
    }).encode()
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash-lite"]
    for model in models:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_KEY}"
        )
        # 2.5-flash: thinking 활성화 (최대 8192 토큰), 나머지는 기본
        if "2.5" in model:
            payload = json.loads(body)
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 16384}
            req_body = json.dumps(payload).encode()
        else:
            req_body = body
        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                result = json.loads(r.read())
            # gemini-2.5-flash는 thinking 파트를 먼저 반환 → thought=True 파트 건너뜀
            parts = result["candidates"][0]["content"]["parts"]
            text = ""
            for part in parts:
                if not part.get("thought", False) and part.get("text", "").strip():
                    text = part["text"].strip()
                    break
            if not text:
                print(f"Gemini {model}: 텍스트 파트 없음 (parts 수={len(parts)})")
                continue
            text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
            text = re.sub(r'#+\s*', '', text)
            text = re.sub(r'`+', '', text)
            print(f"Gemini 성공 ({model})")
            return text
        except urllib.error.HTTPError as e:
            body_err = e.read().decode()[:300]
            print(f"Gemini {model} HTTP {e.code}: {body_err}")
            if e.code == 503:
                import time; time.sleep(15)  # 과부하 시 15초 대기 후 재시도
                continue
        except Exception as e:
            print(f"Gemini {model} 실패: {e}")
    return None


def idx_line(name):
    q = index_q.get(name)
    if not q:
        return "조회 실패"
    return f"{q['price']:,.2f} ({fmt_pct(q['pct'])})"


def mac_str(name, fmt="{:.2f}"):
    q = macro_q.get(name)
    if not q:
        return "조회 실패"
    return f"{fmt.format(q['price'])} ({fmt_pct(q['pct'])})"


# ── MARKETFEED 텔레그램 뉴스 ──
print("MARKETFEED 뉴스 수집 중...")
marketfeed_news = scrape_tg_channel("marketfeed", limit=10)

# ── 종목 뉴스 수집 ──
print("종목 뉴스 수집 중...")
sector_news = {}
for ticker, info in focus_sectors:
    headlines = []
    for sym in SECTOR_STOCKS.get(ticker, []):
        for title in fetch_stock_news(sym, limit=2):
            headlines.append(f"{sym}: {title}")
    sector_news[ticker] = headlines


# ── Gemini 프롬프트 구성 ──
def sector_block(sectors):
    lines = []
    for ticker, info in sectors:
        stocks = SECTOR_STOCKS.get(ticker, [])
        lines.append(f"{info['name']}({ticker}): {info['pct']:+.2f}%")
        for sym in stocks:
            q = stock_data.get(sym)
            if q:
                lines.append(f"  {sym}: {q['price']:,.2f} ({fmt_pct(q['pct'])})")
        news = sector_news.get(ticker, [])
        if news:
            lines.append("  관련뉴스:")
            for n in news[:4]:
                lines.append(f"  - {n}")
    return "\n".join(lines)


prompt = f"""아래 미국 주식 시장 데이터를 보고, 지정된 형식 그대로만 출력하세요.
마크다운 문법(#, **, __, -, ``` 등) 절대 사용 금지. 이모지만 사용 가능.

[날짜] {date_str} ({weekday_kor}요일)

[주요 지수]
S&P 500: {idx_line("S&P 500")}
나스닥: {idx_line("나스닥")}
다우존스: {idx_line("다우존스")}

[시장 뉴스 - MARKETFEED]
{chr(10).join(f"- {n}" for n in marketfeed_news) if marketfeed_news else "수집 실패"}

[강세 상위 3개 섹터 + 주요 종목 + Yahoo Finance 뉴스]
{sector_block(top3)}

[약세 하위 3개 섹터 + 주요 종목 + Yahoo Finance 뉴스]
{sector_block(bot3)}

[출력 규칙]
1. 아래 형식 그대로 출력. 다른 텍스트 추가 금지.
2. 종목 등락률은 위 데이터에서 실제 수치를 그대로 사용.
3. 분석 근거는 위 뉴스 헤드라인에서 구체적 내용을 인용.
4. 각 섹터 분석은 3문장: ①주요 종목 등락률 나열 ②뉴스 기반 원인 ③투자 심리 해석.

[출력 형식 예시 - 이 구조 그대로]
🏭 섹터 흐름 분석

강세 섹터 ▲
• 섹터명(티커) +X.XX%: 종목A ▲X.XX%, 종목B ▼X.XX%, 종목C ▲X.XX%. 뉴스에서 [구체적 헤드라인 내용] 보도되며 매수세 유입. [추가 분석 1문장].
• 섹터명(티커) +X.XX%: 종목A ▲X.XX%, 종목B ▲X.XX%, 종목C ▼X.XX%. 뉴스에서 [구체적 헤드라인 내용] 영향으로 섹터 상승. [추가 분석 1문장].
• 섹터명(티커) +X.XX%: 종목A ▲X.XX%, 종목B ▲X.XX%, 종목C ▲X.XX%. [뉴스 기반 구체적 원인]. [추가 분석 1문장].
• 섹터명(티커) +X.XX%: 종목A ▲X.XX%, 종목B ▲X.XX%, 종목C ▲X.XX%. [뉴스 기반 구체적 원인]. [추가 분석 1문장].
• 섹터명(티커) +X.XX%: 종목A ▲X.XX%, 종목B ▲X.XX%, 종목C ▲X.XX%. [뉴스 기반 구체적 원인]. [추가 분석 1문장].

약세 섹터 ▼
• 섹터명(티커) -X.XX%: 종목A ▼X.XX%, 종목B ▼X.XX%, 종목C ▲X.XX%. [뉴스 기반 구체적 하락 원인]. [추가 분석 1문장].
• 섹터명(티커) -X.XX%: 종목A ▼X.XX%, 종목B ▼X.XX%, 종목C ▼X.XX%. [뉴스 기반 구체적 하락 원인]. [추가 분석 1문장].
• 섹터명(티커) -X.XX%: 종목A ▼X.XX%, 종목B ▼X.XX%, 종목C ▼X.XX%. [뉴스 기반 구체적 하락 원인]. [추가 분석 1문장].

💬 한줄 총평: [오늘 시장 핵심 흐름 한 문장]"""

print("AI 분석 생성 중...")
analysis = call_gemini(prompt)

if not analysis:
    t3 = "\n".join([f"• {q['name']}({t}): {fmt_pct(q['pct'])}" for t, q in top3])
    b3 = "\n".join([f"• {q['name']}({t}): {fmt_pct(q['pct'])}" for t, q in bot3])
    analysis = f"🏭 섹터 흐름\n\n강세 ▲\n{t3}\n\n약세 ▼\n{b3}\n\n💬 한줄 총평: AI 분석 실패"

message = f"""📊 미국 시황 브리핑 [{date_str} ({weekday_kor})]

📈 주요 지수
• S&P 500: {idx_line("S&P 500")}
• 나스닥: {idx_line("나스닥")}
• 다우존스: {idx_line("다우존스")}

{analysis}

🌐 매크로
• 10년물 금리: {mac_str("10년물 금리", "{:.2f}%")}
• 달러 인덱스: {mac_str("달러 인덱스", "{:.2f}")}
• WTI 유가: ${mac_str("WTI 유가", "{:.2f}")}
• VIX: {mac_str("VIX", "{:.2f}")}"""

print("텔레그램 전송 중...")
try:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode()
    req = urllib.request.urlopen(url, data, timeout=15)
    result = json.loads(req.read().decode())
    if result.get("ok"):
        print("텔레그램 전송 성공!")
        print(message)
    else:
        print(f"전송 실패: {result}")
        exit(1)
except Exception as e:
    print(f"텔레그램 전송 오류: {e}")
    exit(1)
