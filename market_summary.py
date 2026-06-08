import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta

TOKEN = "8938660213:AAGZ9E63krSy3hYhJCBi378xpu58bDW4lOQ"
CHAT_ID = "7501066645"

KST = timezone(timedelta(hours=9))
today = datetime.now(KST)
weekday = today.weekday()

if weekday >= 5:
    print("오늘은 주말이라 시황 없음.")
    exit(0)

def fetch_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    meta = data["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev = meta["chartPreviousClose"]
    chg = price - prev
    pct = chg / prev * 100
    return {"price": price, "chg": chg, "pct": pct}

def fmt(q, price_fmt="{:,.2f}"):
    sign = "▲" if q["chg"] >= 0 else "▼"
    return f"{price_fmt.format(q['price'])} ({sign} {abs(q['pct']):.2f}%)"

symbols = {
    "S&P 500":    ("^GSPC",    "{:,.2f}"),
    "나스닥":      ("^IXIC",    "{:,.2f}"),
    "다우존스":    ("^DJI",     "{:,.2f}"),
    "10년물 금리": ("^TNX",     "{:.2f}%"),
    "달러 인덱스": ("DX-Y.NYB", "{:.2f}"),
    "WTI 유가":   ("CL=F",     "${:.2f}"),
    "VIX":        ("^VIX",     "{:.2f}"),
}

quotes = {}
for name, (sym, _) in symbols.items():
    try:
        quotes[name] = fetch_quote(sym)
    except Exception as e:
        quotes[name] = None
        print(f"[{name}] 조회 실패: {e}")

def val(name):
    q = quotes.get(name)
    if q is None:
        return "조회 실패"
    _, price_fmt = symbols[name]
    return fmt(q, price_fmt)

sp = quotes.get("S&P 500")
if sp:
    if sp["pct"] >= 1:
        sentiment = "강세장 — 전반적으로 위험자산 선호 심리가 우세했습니다."
    elif sp["pct"] >= 0:
        sentiment = "소폭 상승 — 관망세 속 완만한 매수 흐름이 이어졌습니다."
    elif sp["pct"] >= -1:
        sentiment = "소폭 하락 — 차익 실현 매물이 지수를 눌렀습니다."
    else:
        sentiment = "약세장 — 매크로 불확실성으로 전반적인 매도세가 우세했습니다."
else:
    sentiment = "데이터 조회에 일부 문제가 있었습니다."

date_str = today.strftime("%Y년 %m월 %d일")
weekday_kor = ["월", "화", "수", "목", "금", "토", "일"][weekday]

message = f"""📊 미국 시황 브리핑 [{date_str} ({weekday_kor})]

📈 주요 지수
- S&P 500: {val("S&P 500")}
- 나스닥: {val("나스닥")}
- 다우존스: {val("다우존스")}

🌐 매크로
- 10년물 금리: {val("10년물 금리")}
- 달러 인덱스: {val("달러 인덱스")}
- WTI 유가: {val("WTI 유가")}
- VIX: {val("VIX")}

💬 한줄 총평: {sentiment}"""

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": message}).encode()
req = urllib.request.urlopen(url, data, timeout=15)
result = json.loads(req.read().decode())
if result.get("ok"):
    print("텔레그램 전송 성공!")
    print(message)
else:
    print(f"전송 실패: {result}")
    exit(1)
