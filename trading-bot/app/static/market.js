const $ = (selector) => document.querySelector(selector);
const formatPrice = (value, currency) => new Intl.NumberFormat("ko-KR", { style: "currency", currency: currency || "KRW", maximumFractionDigits: 2 }).format(Number(value));
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

async function api(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "시세를 가져오지 못했습니다.");
  return payload;
}

async function loadHealth() {
  try {
    const health = await api("/health");
    if (health.status === "ok") {
      $(".connection").classList.add("connected");
      $("#connection-text").textContent = "토스 API · DB 연결됨";
    }
  } catch { $("#connection-text").textContent = "연결 확인 실패"; }
}

function renderPrices(prices) {
  $("#quote-count").textContent = `${prices.length}개 종목`;
  $("#quote-results").innerHTML = prices.map((price) => `
    <article class="quote-card">
      <p class="quote-symbol">${escapeHtml(price.symbol)}</p>
      <strong>${formatPrice(price.last_price, price.currency)}</strong>
      <p class="quote-currency">${escapeHtml(price.currency)}</p>
      <time>${escapeHtml(price.observed_at.replace("T", " "))}</time>
    </article>`).join("");
}

function formatTradingAmount(value) {
  const numeric = Number(String(value).replaceAll(",", ""));
  return Number.isFinite(numeric) ? `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(numeric)}원` : "-";
}

async function loadTop5() {
  const message = $("#top5-message");
  $("#top5-results").innerHTML = "";
  message.textContent = "시장 TOP5를 불러오는 중입니다.";
  try {
    const ranking = await api("/market/top5");
    message.textContent = ranking.disclaimer;
    $("#top5-results").innerHTML = ranking.items.map((item) => `
      <article class="top5-card">
        <span class="rank-number">${item.rank}</span>
        <div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.symbol)}</p></div>
        <div class="top5-price"><strong>${formatPrice(item.price, item.currency)}</strong><em>+${Number(item.change_rate).toFixed(2)}%</em><span>거래대금 ${formatTradingAmount(item.trading_amount)}</span></div>
      </article>`).join("");
  } catch (error) { message.textContent = error.message; }
}

let activeChartSymbol = "005930";

function chartNumber(value) {
  const number = Number(String(value).replaceAll(",", ""));
  return Number.isFinite(number) ? number : null;
}

function renderPriceChart(chart) {
  const current = chartNumber(chart.current_price);
  const points = chart.points.map((point) => ({ ...point, value: chartNumber(point.close_price) }))
    .filter((point) => point.value != null);
  const currentDate = String(chart.observed_at).slice(0, 10);
  if (current != null) {
    const finalPoint = points.at(-1);
    if (finalPoint && String(finalPoint.timestamp).slice(0, 10) === currentDate) finalPoint.value = current;
    else points.push({ timestamp: chart.observed_at, value: current });
  }
  if (points.length < 2) throw new Error("차트를 표시할 가격 데이터가 부족합니다.");

  const width = 720;
  const height = 260;
  const pad = { top: 24, right: 24, bottom: 36, left: 74 };
  const values = points.map((point) => point.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const spread = Math.max(high - low, Math.max(high * 0.01, 1));
  const min = low - spread * 0.15;
  const max = high + spread * 0.15;
  const x = (index) => pad.left + (index / (points.length - 1)) * (width - pad.left - pad.right);
  const y = (value) => pad.top + ((max - value) / (max - min)) * (height - pad.top - pad.bottom);
  const path = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
  const grid = [0, 0.5, 1].map((ratio) => {
    const value = max - (max - min) * ratio;
    const lineY = y(value).toFixed(1);
    return `<line x1="${pad.left}" x2="${width - pad.right}" y1="${lineY}" y2="${lineY}" class="chart-grid" /><text x="${pad.left - 10}" y="${Number(lineY) + 4}" class="chart-axis">${Math.round(value).toLocaleString("ko-KR")}</text>`;
  }).join("");
  const labels = [0, Math.floor((points.length - 1) / 2), points.length - 1].map((index) => `<text x="${x(index)}" y="${height - 12}" text-anchor="middle" class="chart-axis">${escapeHtml(String(points[index].timestamp).slice(5, 10))}</text>`).join("");
  const last = points.at(-1);
  $("#price-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#4b90ff" stop-opacity=".35"/><stop offset="100%" stop-color="#4b90ff" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${path} L${x(points.length - 1)},${height - pad.bottom} L${x(0)},${height - pad.bottom} Z" fill="url(#chart-fill)"/><path d="${path}" class="chart-line"/><circle cx="${x(points.length - 1)}" cy="${y(last.value)}" r="5" class="chart-dot"/>${labels}</svg>`;
}

async function loadChart(symbol = activeChartSymbol) {
  activeChartSymbol = symbol.trim().toUpperCase();
  const message = $("#price-chart-message");
  try {
    const chart = await api(`/market/chart?symbol=${encodeURIComponent(activeChartSymbol)}&count=30`);
    renderPriceChart(chart);
    $("#price-chart-title").textContent = `${chart.symbol} 가격 흐름`;
    $("#chart-current-price").textContent = formatPrice(chart.current_price, chart.currency);
    $("#chart-observed-at").textContent = `현재가 ${String(chart.observed_at).replace("T", " ")}`;
    $("#price-chart-status").textContent = `${chart.refresh_seconds}초마다 현재가 갱신`;
    message.textContent = "일봉 종가 흐름에 최신 현재가를 반영한 참고용 차트입니다.";
  } catch (error) {
    $("#price-chart-status").textContent = "조회 실패";
    message.textContent = error.message;
  }
}

$("#quote-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const symbols = $("#symbols-input").value.trim();
  const message = $("#quote-message");
  $("#quote-results").innerHTML = "";
  $("#quote-count").textContent = "조회 중";
  message.textContent = "토스증권 시세를 조회하고 있습니다.";
  try {
    const { prices } = await api(`/market/prices?symbols=${encodeURIComponent(symbols)}`);
    message.textContent = prices.length ? "최신 조회 결과입니다." : "조회된 종목이 없습니다.";
    renderPrices(prices);
    if (prices[0]) await loadChart(prices[0].symbol);
  } catch (error) {
    $("#quote-count").textContent = "조회 실패";
    message.textContent = error.message;
  }
});

$("#top5-refresh").addEventListener("click", loadTop5);

loadHealth(); loadTop5(); loadChart();
setInterval(() => loadChart(), 15000);
