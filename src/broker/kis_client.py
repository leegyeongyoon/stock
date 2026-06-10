"""KIS REST API async client - quotation and trading."""

import asyncio
from datetime import datetime, timedelta

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
    ORDERBOOK_PATH,
    PRICE_PATH,
    PSBL_ORDER_PATH,
    TR_ORDERBOOK,
    TR_VOLUME_RANK,
    VOLUME_RANK_PATH,
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
    OrderFlow,
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

    @staticmethod
    def _to_int(v) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _price_from_book(o: dict) -> int:
        """호가 응답에서 현재가 추정: stck_prpr 없으면 최우선 매수/매도 중간값."""
        p = KISClient._to_int(o.get("stck_prpr"))
        if p:
            return p
        bid1 = KISClient._to_int(o.get("bidp1"))
        ask1 = KISClient._to_int(o.get("askp1"))
        if bid1 and ask1:
            return (bid1 + ask1) // 2
        return bid1 or ask1

    async def get_orderflow(self, stock_code: str) -> OrderFlow:
        """호가 총잔량 → 잔량비 (호가 API 1콜). 체결강도는 실시간 WS(H0STCNT0)에서.

        실측 확인: 체결강도/잔량은 현재가 API(inquire-price)엔 없고 호가 API에 있음.
        """
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        data = await self._get(ORDERBOOK_PATH, TR_ORDERBOOK, params)
        o = data.get("output1", {})
        return OrderFlow(
            code=stock_code,
            current_price=self._price_from_book(o),
            total_bid_qty=self._to_int(o.get("total_bidp_rsqn")),
            total_ask_qty=self._to_int(o.get("total_askp_rsqn")),
        )

    async def get_volume_rank(
        self, market: str = "ALL", blng: str = "surge", top_n: int = 30,
    ) -> list[dict]:
        """오늘 거래량 순위 — '거래량 폭발' 종목 선별. blng: surge(증가율)/volume/value.

        반환: [{code, name, price, change_rate, volume}, ...]
        """
        iscd = {"ALL": "0000", "KOSPI": "0001", "KOSDAQ": "1001"}.get(market, "0000")
        blng_code = {"volume": "0", "surge": "1", "turnover": "2", "value": "3"}.get(blng, "1")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": iscd, "FID_DIV_CLS_CODE": "0", "FID_BLNG_CLS_CODE": blng_code,
            "FID_TRGT_CLS_CODE": "111111111", "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": "", "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "", "FID_INPUT_DATE_1": "",
        }
        data = await self._get(VOLUME_RANK_PATH, TR_VOLUME_RANK, params)
        out = data.get("output", []) or []
        result = []
        for r in out[:top_n]:
            code = r.get("mksc_shrn_iscd")
            if not code:
                continue
            result.append({
                "code": code, "name": r.get("hts_kor_isnm", ""),
                "price": self._to_int(r.get("stck_prpr")),
                "change_rate": float(r.get("prdy_ctrt", 0) or 0),
                "volume": self._to_int(r.get("acml_vol")),
            })
        return result

    async def get_orderbook(self, stock_code: str) -> OrderFlow:
        """10단계 호가 + 잔량 (호가 API). 깊이 분석용."""
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        data = await self._get(ORDERBOOK_PATH, TR_ORDERBOOK, params)
        o = data.get("output1", {})
        asks = [
            (self._to_int(o.get(f"askp{i}")), self._to_int(o.get(f"askp_rsqn{i}")))
            for i in range(1, 11)
        ]
        bids = [
            (self._to_int(o.get(f"bidp{i}")), self._to_int(o.get(f"bidp_rsqn{i}")))
            for i in range(1, 11)
        ]
        return OrderFlow(
            code=stock_code,
            current_price=self._price_from_book(o),
            total_bid_qty=self._to_int(o.get("total_bidp_rsqn")),
            total_ask_qty=self._to_int(o.get("total_askp_rsqn")),
            asks=asks,
            bids=bids,
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

    async def get_intraday_full_day(
        self,
        stock_code: str,
        time_unit: str = "1",
        market_open: str = "090000",
        market_close: str = "153000",
        max_batches: int = 12,
    ) -> list[MinuteBar]:
        """당일 전 세션 분봉을 FID_INPUT_HOUR_1 역방향 페이징으로 복원.

        KIS 분봉 API는 한 번에 ~120봉, 당일만 제공하므로 끝시각→시작시각으로 내려가며 모은다.
        과거일 백필은 불가(전진 수집 전용). 장마감 스냅샷 배치에서 사용.
        """
        collected: dict[datetime, MinuteBar] = {}
        cursor = market_close

        for _ in range(max_batches):
            params = {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_HOUR_1": cursor,
                "FID_PW_DATA_INCU_YN": "N",
            }
            # 모의(VTS) 시세서버는 간헐적 500 → 페이지별 재시도
            data = None
            for attempt in range(3):
                try:
                    data = await self._get(MINUTE_CHART_PATH, TR_MINUTE_CHART, params)
                    break
                except Exception:  # noqa: BLE001
                    if attempt < 2:
                        await asyncio.sleep(0.4)
            if data is None:
                break
            output2 = data.get("output2", [])
            if not output2:
                break

            batch: list[MinuteBar] = []
            for item in output2:
                try:
                    dt = datetime.strptime(
                        f"{item['stck_bsop_date']}{item['stck_cntg_hour']}", "%Y%m%d%H%M%S"
                    )
                    batch.append(MinuteBar(
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

            if not batch:
                break

            new_count = 0
            for b in batch:
                if b.datetime not in collected:
                    collected[b.datetime] = b
                    new_count += 1

            earliest = min(b.datetime for b in batch)
            if new_count == 0 or earliest.strftime("%H%M%S") <= market_open:
                break
            cursor = (earliest - timedelta(minutes=1)).strftime("%H%M%S")

        return sorted(collected.values(), key=lambda b: b.datetime)

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
        is_first = True

        while True:
            params = {
                "CANO": self.auth.account_prefix,
                "ACNT_PRDT_CD": self.auth.account_suffix,
                "INQR_STRT_DT": start,
                "INQR_END_DT": end,
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": "",
                "CCLD_DVSN": "01",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": ctx_fk100,
                "CTX_AREA_NK100": ctx_nk100,
            }

            try:
                await self._rate_limit()
                headers = self.auth.get_auth_headers()
                headers["tr_id"] = self._tr_ccld()
                headers["tr_cont"] = "" if is_first else "N"
                is_first = False

                async with self._semaphore:
                    resp = await self._client.get(
                        CCLD_PATH, headers=headers, params=params,
                    )

                if resp.status_code != 200:
                    body = resp.text
                    logger.warning(
                        f"체결내역 조회 HTTP {resp.status_code} "
                        f"({start}~{end}): {body[:500]}"
                    )
                    break

                data = resp.json()
                rt_cd = data.get("rt_cd", "")
                if rt_cd != "0":
                    logger.warning(
                        f"체결내역 조회 실패 rt_cd={rt_cd}, "
                        f"msg={data.get('msg1', '')}"
                    )
                    break

            except Exception as e:
                logger.warning(f"체결내역 조회 예외 ({start}~{end}): {e}")
                break

            output1 = data.get("output1", [])

            page_buys = 0
            page_sells = 0
            for item in output1:
                qty = int(item.get("tot_ccld_qty", 0))
                if qty <= 0:
                    continue
                side_code = item.get("sll_buy_dvsn_cd", "")
                is_buy = side_code == "02"
                if is_buy:
                    page_buys += 1
                else:
                    page_sells += 1
                executions.append(ExecutionInfo(
                    order_id=item.get("odno", ""),
                    stock_code=item.get("pdno", ""),
                    stock_name=item.get("prdt_name", ""),
                    side="매수" if is_buy else "매도",
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

            logger.info(
                f"체결내역 페이지 ({start}~{end}): "
                f"output1={len(output1)}건 (매수{page_buys}/매도{page_sells}), "
                f"tr_cont={tr_cont!r}, fk={next_fk!r}"
            )

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
