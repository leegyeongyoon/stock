"""KIS API constants - URLs, transaction IDs, error codes."""

# ── Base URLs ──────────────────────────────────────────────
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
MOCK_BASE_URL = "https://openapivts.koreainvestment.com:29443"

REAL_WS_URL = "ws://ops.koreainvestment.com:21000"
MOCK_WS_URL = "ws://ops.koreainvestment.com:31000"

# ── Auth ───────────────────────────────────────────────────
TOKEN_PATH = "/oauth2/tokenP"
TOKEN_REVOKE_PATH = "/oauth2/revokeP"

# ── Quotation (시세) ──────────────────────────────────────
PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
MINUTE_CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
DAILY_CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
ORDERBOOK_PATH = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"

# ── Trading (매매) ─────────────────────────────────────────
ORDER_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
ORDER_MODIFY_PATH = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
CCLD_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
PSBL_ORDER_PATH = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"

# ── Transaction IDs (tr_id) ────────────────────────────────
# 실전투자
TR_PRICE = "FHKST01010100"           # 현재가 조회
TR_MINUTE_CHART = "FHKST03010200"    # 분봉 조회
TR_DAILY_CHART = "FHKST03010100"     # 일봉 조회
TR_ORDERBOOK = "FHKST01010200"       # 호가 조회

TR_BUY = "TTTC0802U"                 # 매수 주문 (실전)
TR_SELL = "TTTC0801U"                # 매도 주문 (실전)
TR_MODIFY = "TTTC0803U"              # 정정/취소 (실전)
TR_BALANCE = "TTTC8434R"             # 잔고 조회 (실전)
TR_CCLD = "TTTC8001R"                # 체결 내역 (실전)
TR_PSBL_ORDER = "TTTC8908R"          # 주문 가능 조회 (실전)

# 모의투자
TR_BUY_MOCK = "VTTC0802U"            # 매수 주문 (모의)
TR_SELL_MOCK = "VTTC0801U"           # 매도 주문 (모의)
TR_MODIFY_MOCK = "VTTC0803U"         # 정정/취소 (모의)
TR_BALANCE_MOCK = "VTTC8434R"        # 잔고 조회 (모의)
TR_CCLD_MOCK = "VTTC8001R"           # 체결 내역 (모의)
TR_PSBL_ORDER_MOCK = "VTTC8908R"     # 주문 가능 조회 (모의)

# ── WebSocket Subscription Keys ────────────────────────────
WS_TRADE = "H0STCNT0"                # 실시간 체결가
WS_ORDERBOOK = "H0STASP0"            # 실시간 호가
WS_MY_TRADE = "H0STCNI0"             # 내 체결 통보 (실전)
WS_MY_TRADE_MOCK = "H0STCNI9"        # 내 체결 통보 (모의)

# ── Order Types ────────────────────────────────────────────
ORD_TYPE_MARKET = "01"                # 시장가
ORD_TYPE_LIMIT = "00"                 # 지정가

# ── Exchange Codes ─────────────────────────────────────────
EXCHANGE_KRX = "KRX"

# ── Rate Limit ─────────────────────────────────────────────
RATE_LIMIT_PER_SEC = 20               # KIS 초당 20회 제한
WS_MAX_SUBSCRIPTIONS = 40             # WebSocket 최대 40종목

# ── Error Codes ────────────────────────────────────────────
ERROR_CODES = {
    "0": "정상",
    "EGW00121": "유효하지 않은 토큰",
    "EGW00123": "토큰 만료",
    "IGW00121": "유효하지 않은 접근토큰",
    "EGW00201": "초당 거래건수 초과",
}
