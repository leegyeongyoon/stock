"""네이버 증권 테마 크롤러"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from loguru import logger


@dataclass
class ThemeStock:
    """테마 내 종목 정보"""
    code: str
    name: str
    price: int
    change_rate: float  # 등락률 (%)
    volume: int  # 거래량
    market_cap: int  # 시가총액 (억원)
    foreign_rate: float = 0.0  # 외인 보유비율 (%)
    foreign_change: int = 0  # 외인 순매수 (주)
    inst_change: int = 0  # 기관 순매수 (주)


@dataclass
class Theme:
    """테마 정보"""
    code: str
    name: str
    change_rate: float  # 테마 평균 등락률
    total_volume: int  # 총 거래량
    total_market_cap: int  # 총 시가총액
    stock_count: int  # 종목 수
    up_count: int  # 상승 종목 수
    down_count: int  # 하락 종목 수
    stocks: list[ThemeStock] = field(default_factory=list)
    leader_stock: Optional[str] = None  # 대장주


class NaverThemeCrawler:
    """네이버 증권 테마 크롤러"""

    BASE_URL = "https://finance.naver.com"
    THEME_LIST_URL = f"{BASE_URL}/sise/theme.naver"
    THEME_DETAIL_URL = f"{BASE_URL}/sise/sise_group_detail.naver"
    STOCK_URL = f"{BASE_URL}/item/main.naver"

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
            timeout=30.0
        )

    async def close(self):
        await self.client.aclose()

    async def get_theme_list(self) -> list[Theme]:
        """전체 테마 목록 조회"""
        themes = []

        try:
            # 페이지 1~5 크롤링
            for page in range(1, 6):
                url = f"{self.THEME_LIST_URL}?page={page}"
                resp = await self.client.get(url)
                soup = BeautifulSoup(resp.text, 'html.parser')

                table = soup.find('table', class_='type_1')
                if not table:
                    continue

                rows = table.find_all('tr')
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) < 5:
                        continue

                    # 테마 링크에서 코드 추출
                    link = cols[0].find('a')
                    if not link:
                        continue

                    href = link.get('href', '')
                    if 'no=' not in href:
                        continue

                    theme_code = href.split('no=')[1].split('&')[0]
                    theme_name = link.text.strip()

                    # 등락률
                    change_text = cols[2].text.strip().replace('%', '').replace('+', '')
                    try:
                        change_rate = float(change_text)
                    except:
                        change_rate = 0.0

                    themes.append(Theme(
                        code=theme_code,
                        name=theme_name,
                        change_rate=change_rate,
                        total_volume=0,
                        total_market_cap=0,
                        stock_count=0,
                        up_count=0,
                        down_count=0
                    ))

            logger.info(f"테마 {len(themes)}개 조회 완료")
            return themes

        except Exception as e:
            logger.error(f"테마 목록 조회 실패: {e}")
            return []

    async def get_theme_stocks(self, theme_code: str) -> list[ThemeStock]:
        """특정 테마의 종목 목록 조회"""
        stocks = []

        try:
            url = f"{self.THEME_DETAIL_URL}?type=theme&no={theme_code}"
            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, 'html.parser')

            table = soup.find('table', class_='type_5')
            if not table:
                return stocks

            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 6:
                    continue

                # 종목 링크
                link = cols[0].find('a')
                if not link:
                    continue

                href = link.get('href', '')
                if 'code=' not in href:
                    continue

                stock_code = href.split('code=')[1].split('&')[0]
                stock_name = link.text.strip()

                # 현재가
                try:
                    price = int(cols[1].text.strip().replace(',', ''))
                except:
                    price = 0

                # 등락률
                try:
                    change_text = cols[3].text.strip().replace('%', '').replace('+', '')
                    change_rate = float(change_text)
                except:
                    change_rate = 0.0

                # 거래량
                try:
                    volume = int(cols[5].text.strip().replace(',', ''))
                except:
                    volume = 0

                stocks.append(ThemeStock(
                    code=stock_code,
                    name=stock_name,
                    price=price,
                    change_rate=change_rate,
                    volume=volume,
                    market_cap=0
                ))

            return stocks

        except Exception as e:
            logger.error(f"테마 종목 조회 실패 ({theme_code}): {e}")
            return []

    async def get_stock_detail(self, stock_code: str) -> dict:
        """종목 상세 정보 (외인/기관 포함)"""
        try:
            url = f"{self.STOCK_URL}?code={stock_code}"
            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, 'html.parser')

            result = {
                'foreign_rate': 0.0,
                'foreign_change': 0,
                'inst_change': 0,
                'market_cap': 0
            }

            # 외국인 보유비율
            foreign_elem = soup.find('em', {'id': 'foreignPercent'})
            if foreign_elem:
                try:
                    result['foreign_rate'] = float(foreign_elem.text.strip().replace('%', ''))
                except:
                    pass

            # 시가총액
            table = soup.find('table', {'summary': '시가총액 정보'})
            if table:
                rows = table.find_all('tr')
                for row in rows:
                    th = row.find('th')
                    td = row.find('td')
                    if th and td and '시가총액' in th.text:
                        try:
                            cap_text = td.text.strip().replace(',', '').replace('억원', '')
                            result['market_cap'] = int(cap_text)
                        except:
                            pass

            return result

        except Exception as e:
            logger.error(f"종목 상세 조회 실패 ({stock_code}): {e}")
            return {}

    async def get_investor_trends(self, stock_code: str) -> dict:
        """외인/기관 매매동향"""
        try:
            url = f"https://finance.naver.com/item/frgn.naver?code={stock_code}"
            resp = await self.client.get(url)
            soup = BeautifulSoup(resp.text, 'html.parser')

            result = {
                'foreign_change': 0,
                'inst_change': 0
            }

            table = soup.find('table', {'summary': '외국인, 기관 순매매 거래량'})
            if table:
                rows = table.find_all('tr')
                if len(rows) >= 2:
                    cols = rows[1].find_all('td')
                    if len(cols) >= 6:
                        try:
                            # 외국인 순매매
                            foreign_text = cols[4].text.strip().replace(',', '').replace('+', '')
                            result['foreign_change'] = int(foreign_text)
                        except:
                            pass
                        try:
                            # 기관 순매매
                            inst_text = cols[5].text.strip().replace(',', '').replace('+', '')
                            result['inst_change'] = int(inst_text)
                        except:
                            pass

            return result

        except Exception as e:
            logger.error(f"투자자 동향 조회 실패 ({stock_code}): {e}")
            return {'foreign_change': 0, 'inst_change': 0}

    async def get_top_themes_with_details(self, top_n: int = 10) -> list[Theme]:
        """상위 테마 + 종목 상세 정보 조회"""
        # 1. 전체 테마 목록
        all_themes = await self.get_theme_list()

        # 2. 등락률 기준 상위 N개 선정
        sorted_themes = sorted(all_themes, key=lambda x: x.change_rate, reverse=True)[:top_n]

        # 3. 각 테마별 종목 조회
        for theme in sorted_themes:
            stocks = await self.get_theme_stocks(theme.code)

            # 상위 5개 종목만 상세 조회
            for stock in stocks[:5]:
                detail = await self.get_stock_detail(stock.code)
                investor = await self.get_investor_trends(stock.code)

                stock.market_cap = detail.get('market_cap', 0)
                stock.foreign_rate = detail.get('foreign_rate', 0.0)
                stock.foreign_change = investor.get('foreign_change', 0)
                stock.inst_change = investor.get('inst_change', 0)

                await asyncio.sleep(0.2)  # Rate limiting

            theme.stocks = stocks[:5]
            theme.stock_count = len(stocks)
            theme.up_count = sum(1 for s in stocks if s.change_rate > 0)
            theme.down_count = sum(1 for s in stocks if s.change_rate < 0)
            theme.total_volume = sum(s.volume for s in stocks)

            # 대장주 선정 (등락률 + 거래량 기준)
            if stocks:
                leader = max(stocks, key=lambda s: s.change_rate * 0.5 + (s.volume / 1000000) * 0.5)
                theme.leader_stock = leader.name

            logger.info(f"테마 '{theme.name}' 분석 완료: {len(stocks)}종목")

        return sorted_themes


async def main():
    """테스트 실행"""
    crawler = NaverThemeCrawler()

    try:
        print("테마 분석 시작...")
        themes = await crawler.get_top_themes_with_details(top_n=5)

        for theme in themes:
            print(f"\n{'='*50}")
            print(f"📌 {theme.name} ({theme.change_rate:+.2f}%)")
            print(f"   종목수: {theme.stock_count} | 상승: {theme.up_count} | 하락: {theme.down_count}")
            print(f"   대장주: {theme.leader_stock}")
            print(f"   {'─'*40}")

            for stock in theme.stocks:
                print(f"   {stock.name:12} | {stock.change_rate:+6.2f}% | "
                      f"거래량: {stock.volume:>10,} | "
                      f"외인: {stock.foreign_change:+,} | "
                      f"기관: {stock.inst_change:+,}")

    finally:
        await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())
