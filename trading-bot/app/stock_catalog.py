"""Public KRX listed-company catalog loader used for local name search."""

from dataclasses import dataclass
from html.parser import HTMLParser

import httpx


KRX_LISTED_COMPANY_URL = (
    "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
)


class StockCatalogError(RuntimeError):
    """Raised when the public KRX company catalog cannot be loaded safely."""


@dataclass(frozen=True)
class CatalogStock:
    stock_code: str
    name: str
    market: str


class _KrxTableParser(HTMLParser):
    """Minimal dependency-free parser for KRX's downloadable HTML table."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None


class KrxCatalogClient:
    """Fetch currently listed Korean companies from KRX's public catalog."""

    def fetch_listed_stocks(self) -> list[CatalogStock]:
        try:
            response = httpx.get(KRX_LISTED_COMPANY_URL, timeout=30.0)
            response.raise_for_status()
            html = response.content.decode("euc-kr")
        except (httpx.HTTPError, UnicodeDecodeError) as error:
            raise StockCatalogError("KRX 상장법인 목록을 가져오지 못했습니다.") from error

        parser = _KrxTableParser()
        parser.feed(html)
        if len(parser.rows) < 2:
            raise StockCatalogError("KRX 상장법인 목록 형식을 확인하지 못했습니다.")

        stocks: list[CatalogStock] = []
        for row in parser.rows[1:]:
            if len(row) < 3:
                continue
            name, market, stock_code = row[0].strip(), row[1].strip(), row[2].strip().upper()
            if not name or not stock_code:
                continue
            stocks.append(CatalogStock(stock_code=stock_code, name=name, market=market))
        if not stocks:
            raise StockCatalogError("KRX 상장법인 목록에 유효한 종목이 없습니다.")
        return stocks
