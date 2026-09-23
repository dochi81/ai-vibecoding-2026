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
  } catch (error) {
    $("#quote-count").textContent = "조회 실패";
    message.textContent = error.message;
  }
});

$("#top5-refresh").addEventListener("click", loadTop5);

loadHealth(); loadTop5();
