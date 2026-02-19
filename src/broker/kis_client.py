"""KIS REST API async client - quotation and trading."""

import asyncio
from datetime import datetime

import httpx
from loguru import logger

from src.broker.kis_auth import KISAuth
from src.broker.kis_constants import (
    BALANCE_PATH,
    CCLD_PATH,
    MINUTE_CHART_PATH,
    ORDER_MODIFY_PATH,
    ORDER_PATH,
    ORD_TYPE_LIMIT,
    ORD_TYPE_MARKET,
    PRICE_PATH,
    PSBL_ORDER_PATH,
    TR_BALANCE,
    TR_BALANCE_MOCK,
    TR_BUY,
    TR_BUY_MOCK,
    TR_CCLD,
    TR_CCLD_MOCK,
    TR_MINUTE_CHART,
    TR_MODIFY,
    TR_MODIFY_MOCK,
    TR_PRICE,
    TR_PSBL_ORDER,
    TR_PSBL_ORDER_MOCK,
    TR_SELL,
    TR_SELL_MOCK,
)
from src.broker.kis_models import (
    AccountBalance,
    BalanceItem,
    ExecutionInfo,
    MinuteBar,
    OrderRequest,
    OrderResponse,
    OrderSide,
    StockPrice,
)


class KISClient:
    """Async HTTP client for KIS REST API."""

    def __init__(self, auth: KISAuth):
        self.auth = auth
        self._semaphore = asyncio.Semaphore(10)
        self._last_call_time: float = 0.0
        self._rate_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize HTTP client and authenticate."""
        self._client = httpx.AsyncClient(
            base_url=self.auth.base_url,
            timeout=15.0,
        )
        await self.auth.get_access_token()
        logger.info("KIS REST 클라이언트 시작")

    async def stop(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("KIS REST 클라이언트 종료")

    async def _rate_limit(self) -> None:
        """Enforce ~20 req/sec rate limit."""
        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_call_time
            if elapsed < 0.05:  # 50ms minimum gap
                await asyncio.sleep(0.05 - elapsed)
            self._last_call_time = asyncio.get_event_loop().time()

    async def _get(
        self, path: str, tr_id: str, params: dict | None = None
    ) -> dict:
        """Rate-limited GET request."""
        await self._rate_limit()
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = tr_id

        async with self._semaphore:
            resp = await self._client.get(path, headers=headers, params=params or {})
            resp.raise_for_status()
            data = resp.json()
            # 잔고 조회 디버그 로깅
            if "balance" in path.lower() or "8434" in tr_id:
                logger.info(f"KIS 잔고 API 응답: rt_cd={data.get('rt_cd')}, msg={data.get('msg1')}, output2={data.get('output2', [])[:1]}")
            return data

    async def _post(
        self, path: str, tr_id: str, body: dict | None = None
    ) -> dict:
        """Rate-limited POST request."""
        await self._rate_limit()
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = tr_id

        async with self._semaphore:
            resp = await self._client.post(path, headers=headers, json=body or {})
            resp.raise_for_status()
            return resp.json()

    # ── WebSocket Approval Key ──────────────────────────────

    async def get_ws_approval_key(self) -> str:
        """Get WebSocket approval key from KIS API."""
        path = "/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.auth.app_key,
            "secretkey": self.auth.app_secret,
        }
        async with self._semaphore:
            resp = await self._client.post(path, json=body)
            resp.raise_for_status()
            data = resp.json()
        key = data.get("approval_key", "")
        if not key:
            raise RuntimeError(f"WS approval key 발급 실패: {data}")
        logger.info("KIS WebSocket approval key 발급 완료")
        return key

    # ── Quotation APIs ─────────────────────────────────────

    async def get_current_price(self, stock_code: str) -> StockPrice:
        """Get current stock price (현재가 조회)."""
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }
        data = await self._get(PRICE_PATH, TR_PRICE, params)
        output = data.get("output", {})

        return StockPrice(
            code=stock_code,
            name=output.get("hts_kor_isnm", ""),
            current_price=int(output.get("stck_prpr", 0)),
            open_price=int(output.get("stck_oprc", 0)),
            high_price=int(output.get("stck_hgpr", 0)),
            low_price=int(output.get("stck_lwpr", 0)),
            volume=int(output.get("acml_vol", 0)),
            change_rate=float(output.get("prdy_ctrt", 0)),
        )

    async def get_minute_bars(
        self,
        stock_code: str,
        time_unit: str = "5",
        count: int = 30,
    ) -> list[MinuteBar]:
        """Get minute chart data (분봉 조회). time_unit: '1','3','5','10','15','30','60'."""
        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": datetime.now().strftime("%H%M%S"),
            "FID_PW_DATA_INCU_YN": "N",
        }
        data = await self._get(MINUTE_CHART_PATH, TR_MINUTE_CHART, params)
        output2 = data.get("output2", [])

        bars = []
        for item in output2[:count]:
            try:
                dt_str = f"{item['stck_bsop_date']}{item['stck_cntg_hour']}"
                dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
                bars.append(MinuteBar(
                    code=stock_code,
                    datetime=dt,
                    open=int(item.get("stck_oprc", 0)),
                    high=int(item.get("stck_hgpr", 0)),
                    low=int(item.get("stck_lwpr", 0)),
                    close=int(item.get("stck_prpr", 0)),
                    volume=int(item.get("cntg_vol", 0)),
                ))
            except (KeyError, ValueError):
                continue

        bars.reverse()
        return bars

    # ── Trading APIs ───────────────────────────────────────

    def _tr_buy(self) -> str:
        return TR_BUY_MOCK if self.auth.is_mock else TR_BUY

    def _tr_sell(self) -> str:
        return TR_SELL_MOCK if self.auth.is_mock else TR_SELL

    def _tr_modify(self) -> str:
        return TR_MODIFY_MOCK if self.auth.is_mock else TR_MODIFY

    def _tr_balance(self) -> str:
        return TR_BALANCE_MOCK if self.auth.is_mock else TR_BALANCE

    def _tr_ccld(self) -> str:
        return TR_CCLD_MOCK if self.auth.is_mock else TR_CCLD

    def _tr_psbl(self) -> str:
        return TR_PSBL_ORDER_MOCK if self.auth.is_mock else TR_PSBL_ORDER

    async def place_order(self, req: OrderRequest) -> OrderResponse:
        """Place a buy or sell order."""
        tr_id = self._tr_buy() if req.side == OrderSide.BUY else self._tr_sell()

        body = {
            "CANO": self.auth.account_prefix,
            "ACNT_PRDT_CD": self.auth.account_suffix,
            "PDNO": req.stock_code,
            "ORD_DVSN": req.order_type.value,
            "ORD_QTY": str(req.quantity),
            "ORD_UNPR": str(req.price) if req.order_type == ORD_TYPE_LIMIT else "0",
        }

        try:
            data = await self._post(ORDER_PATH, tr_id, body)
            output = data.get("output", {})
            rt_cd = data.get("rt_cd", "")
            msg = data.get("msg1", "")

            success = rt_cd == "0"
            if not success:
                logger.warning(
                    f"주문 실패: {req.stock_code} {req.side.value} "
                    f"rt_cd={rt_cd} msg={msg}"
                )

            return OrderResponse(
                success=success,
                order_id=output.get("ODNO", ""),
                message=msg,
                rt_cd=rt_cd,
                msg_cd=data.get("msg_cd", ""),
                order_number=output.get("ODNO", ""),
                order_time=output.get("ORD_TMD", ""),
            )
        except Exception as e:
            logger.error(f"주문 요청 오류: {req.stock_code} {req.side.value} - {e}")
            return OrderResponse(success=False, message=str(e))

    async def cancel_order(
        self, order_number: str, stock_code: str, quantity: int
    ) -> OrderResponse:
        """Cancel an open order."""
        body = {
            "CANO": self.auth.account_prefix,
            "ACNT_PRDT_CD": self.auth.account_suffix,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_number,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }

        try:
            data = await self._post(ORDER_MODIFY_PATH, self._tr_modify(), body)
            rt_cd = data.get("rt_cd", "")
            return OrderResponse(
                success=rt_cd == "0",
                order_id=data.get("output", {}).get("ODNO", ""),
                message=data.get("msg1", ""),
                rt_cd=rt_cd,
            )
        except Exception as e:
            logger.error(f"주문 취소 오류: order={order_number} - {e}")
            return OrderResponse(success=False, message=str(e))

    async def get_balance(self) -> AccountBalance:
        """Get account balance and holdings (잔고 조회)."""
        params = {
            "CANO": self.auth.account_prefix,
            "ACNT_PRDT_CD": self.auth.account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = await self._get(BALANCE_PATH, self._tr_balance(), params)

        # KIS API 에러 체크 (rt_cd="0"이 성공)
        rt_cd = data.get("rt_cd", "1")
        if rt_cd != "0":
            msg = data.get("msg1", "알 수 없는 오류")
            logger.warning(f"KIS 잔고 조회 실패: rt_cd={rt_cd}, msg={msg}")
            raise RuntimeError(f"KIS 잔고 조회 실패: {msg}")

        output1 = data.get("output1", [])
        output2 = data.get("output2", [{}])

        holdings = []
        for item in output1:
            qty = int(item.get("hldg_qty", 0))
            if qty <= 0:
                continue
            holdings.append(BalanceItem(
                stock_code=item.get("pdno", ""),
                stock_name=item.get("prdt_name", ""),
                quantity=qty,
                avg_price=float(item.get("pchs_avg_pric", 0)),
                current_price=int(item.get("prpr", 0)),
                eval_amount=int(item.get("evlu_amt", 0)),
                pnl=int(item.get("evlu_pfls_amt", 0)),
                pnl_rate=float(item.get("evlu_pfls_rt", 0)),
            ))

        summary = output2[0] if output2 else {}
        return AccountBalance(
            total_eval=int(summary.get("tot_evlu_amt", 0)),
            total_deposit=int(summary.get("dnca_tot_amt", 0)),
            total_pnl=int(summary.get("evlu_pfls_smtl_amt", 0)),
            total_pnl_rate=float(summary.get("tot_evlu_pfls_rt", 0)) if summary.get("tot_evlu_pfls_rt") else 0.0,
            purchase_total=int(summary.get("pchs_amt_smtl_amt", 0)),
            net_asset=int(summary.get("nass_amt", 0)),
            holdings=holdings,
        )

    async def get_executions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[ExecutionInfo]:
        """Get execution history (체결 내역). Supports date range + pagination."""
        today = datetime.now().strftime("%Y%m%d")
        start = start_date or today
        end = end_date or today

        executions: list[ExecutionInfo] = []
        ctx_fk100 = ""
        ctx_nk100 = ""

        while True:
            params = {
                "CANO": self.auth.account_prefix,
                "ACNT_PRDT_CD": self.auth.account_suffix,
                "INQR_STRT_DT": start,
                "INQR_END_DT": end,
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": "",
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": ctx_fk100,
                "CTX_AREA_NK100": ctx_nk100,
            }
            data = await self._get(CCLD_PATH, self._tr_ccld(), params)
            output1 = data.get("output1", [])

            for item in output1:
                qty = int(item.get("tot_ccld_qty", 0))
                if qty <= 0:
                    continue
                executions.append(ExecutionInfo(
                    order_id=item.get("odno", ""),
                    stock_code=item.get("pdno", ""),
                    stock_name=item.get("prdt_name", ""),
                    side="매수" if item.get("sll_buy_dvsn_cd") == "02" else "매도",
                    quantity=qty,
                    price=int(item.get("avg_prvs", 0)),
                    total_amount=int(item.get("tot_ccld_amt", 0)),
                    order_time=item.get("ord_tmd", ""),
                    order_type=item.get("ord_dvsn_name", ""),
                    order_quantity=int(item.get("ord_qty", 0)),
                ))

            # 연속조회: tr_cont가 "M" or "F"이면 다음 페이지 존재
            tr_cont = data.get("tr_cont", "")
            next_fk = data.get("ctx_area_fk100", "").strip()
            next_nk = data.get("ctx_area_nk100", "").strip()

            if tr_cont not in ("M", "F") or not next_fk:
                break

            ctx_fk100 = next_fk
            ctx_nk100 = next_nk

        return executions

    async def get_buyable_amount(self, stock_code: str, price: int) -> int:
        """Get maximum buyable quantity for a stock at given price."""
        params = {
            "CANO": self.auth.account_prefix,
            "ACNT_PRDT_CD": self.auth.account_suffix,
            "PDNO": stock_code,
            "ORD_UNPR": str(price),
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        data = await self._get(PSBL_ORDER_PATH, self._tr_psbl(), params)
        output = data.get("output", {})
        return int(output.get("nrcvb_buy_qty", 0))
