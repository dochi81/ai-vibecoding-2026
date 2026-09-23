const $ = (selector) => document.querySelector(selector);
const toNumber = (value) => {
  if (value == null || value === "") return null;
  const number = Number(String(value).replaceAll(",", ""));
  return Number.isFinite(number) ? number : null;
};
const money = (value) => {
  const numeric = toNumber(value);
  return numeric == null ? "-" : new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 }).format(numeric);
};
const number = (value) => {
  const numeric = toNumber(value);
  return numeric == null ? "-" : new Intl.NumberFormat("ko-KR").format(numeric);
};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "요청을 처리하지 못했습니다.");
  return payload;
}

async function loadHealth() {
  try {
    const health = await api("/health");
    if (health.status === "ok") {
      $(".connection").classList.add("connected");
      $("#connection-text").textContent = "API · DB 연결됨";
    }
  } catch { $("#connection-text").textContent = "연결 확인 실패"; }
}

function renderSummary(summary = {}) {
  const values = [
    summary.marketValue?.amountAfterCost?.krw ?? summary.marketValue?.amount?.krw,
    summary.totalPurchaseAmount?.krw,
    summary.profitLoss?.amountAfterCost?.krw ?? summary.profitLoss?.amount?.krw,
    summary.dailyProfitLoss?.amount?.krw,
  ];
  document.querySelectorAll("#holding-summary strong").forEach((element, index) => {
    const value = values[index];
    element.textContent = money(value);
    const numeric = toNumber(value);
    element.className = numeric != null && numeric > 0 && index > 1 ? "positive" : numeric != null && numeric < 0 && index > 1 ? "negative" : "";
  });
}

function holdingName(item) { return item.name || item.stockName || item.symbol || item.stockCode || "-"; }
function renderHoldings(items = []) {
  const body = $("#holdings-body");
  if (!items.length) { body.innerHTML = '<tr><td colspan="4" class="empty">보유 종목이 없습니다.</td></tr>'; return; }
  body.innerHTML = items.map((item) => {
    const rate = item.profitLossRate ?? item.returnRate;
    const numericRate = toNumber(rate);
    const style = numericRate != null && numericRate > 0 ? "positive" : numericRate != null && numericRate < 0 ? "negative" : "";
    const marketValue = item.marketValue?.amountAfterCost?.krw ?? item.marketValue?.amount?.krw ?? item.marketValue ?? item.evaluationAmount;
    return `<tr><td>${escapeHtml(holdingName(item))}</td><td>${number(item.quantity ?? item.holdingQuantity)}</td><td>${money(marketValue)}</td><td class="${style}">${numericRate == null ? "-" : `${numericRate.toFixed(2)}%`}</td></tr>`;
  }).join("");
}

async function loadHoldings() {
  const accountSeq = $("#account-select").value;
  if (!accountSeq) return;
  $("#holdings-body").innerHTML = '<tr><td colspan="4" class="empty">보유 종목을 불러오는 중입니다.</td></tr>';
  try { const holdings = await api(`/accounts/${encodeURIComponent(accountSeq)}/holdings`); renderSummary(holdings.summary); renderHoldings(holdings.items); }
  catch (error) { $("#holdings-body").innerHTML = `<tr><td colspan="4" class="empty">${error.message}</td></tr>`; }
}

async function loadAccounts() {
  try {
    const { accounts } = await api("/accounts");
    const select = $("#account-select");
    if (!accounts.length) { select.innerHTML = '<option value="">연결된 계좌가 없습니다</option>'; return; }
    select.innerHTML = accounts.map((account) => `<option value="${escapeHtml(account.account_seq)}">${escapeHtml(account.account_type)} · ${escapeHtml(account.account_number)}</option>`).join("");
    await loadHoldings();
  } catch (error) { const message = escapeHtml(error.message); $("#account-select").innerHTML = `<option>${message}</option>`; $("#holdings-body").innerHTML = `<tr><td colspan="4" class="empty">${message}</td></tr>`; }
}

function renderDailyPerformance(performance) {
  $("#daily-performance-date").textContent = performance.date || "오늘";
  $("#daily-trade-count").textContent = `${number(performance.trade_count)}건`;
  $("#daily-buy-amount").textContent = money(performance.buy_amount);
  $("#daily-sell-amount").textContent = money(performance.sell_amount);
  const realized = $("#daily-realized-pl");
  realized.textContent = money(performance.realized_profit_loss);
  const numeric = toNumber(performance.realized_profit_loss);
  realized.className = numeric > 0 ? "positive" : numeric < 0 ? "negative" : "";
}

async function loadDailyPerformance() {
  try { renderDailyPerformance(await api("/paper-performance/daily")); }
  catch (error) { $("#daily-realized-pl").textContent = error.message; }
}

function renderStrategy(decision) {
  $("#strategy-signal").textContent = decision.signal;
  $("#strategy-signal").className = decision.signal === "BUY" ? "positive" : decision.signal === "SELL" ? "negative" : "";
  $("#strategy-average").textContent = money(decision.moving_average);
  const badge = $("#strategy-badge");
  badge.textContent = decision.signal;
  badge.className = decision.signal === "BUY" ? "signal-buy" : decision.signal === "SELL" ? "signal-sell" : "pending";
  $("#strategy-reason").textContent = decision.reason;
}

async function analyzeStrategy(symbol) {
  try { renderStrategy(await api(`/strategy/moving-average?symbol=${encodeURIComponent(symbol)}`)); }
  catch (error) { $("#strategy-badge").textContent = "분석 실패"; $("#strategy-badge").className = "pending"; $("#strategy-reason").textContent = error.message; }
}

$("#price-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const symbol = $("#symbol-input").value.trim(); const result = $("#price-result");
  result.innerHTML = "<span>현재가를 조회하는 중입니다.</span>";
  try { const { prices } = await api(`/market/prices?symbols=${encodeURIComponent(symbol)}`); const price = prices[0]; result.innerHTML = `<span>${escapeHtml(price.symbol)} · ${escapeHtml(price.observed_at.replace("T", " "))}</span><strong>${money(price.last_price)}</strong>`; await analyzeStrategy(price.symbol); }
  catch (error) { result.innerHTML = `<span>${escapeHtml(error.message)}</span>`; }
});
$("#account-select").addEventListener("change", loadHoldings);
$("#account-refresh").addEventListener("click", loadAccounts);

function renderTraderStatus(status) {
  $("#trader-status").textContent = `${status.message} (${status.mode} 모드)`;
  const badge = $("#paper-runtime-badge");
  badge.textContent = status.running ? "모의매매 실행 중" : "모의매매 정지됨";
  badge.className = status.running ? "runtime-running" : "runtime-stopped";
  $("#trader-start").disabled = status.running;
  $("#trader-stop").disabled = !status.running;
  $("#paper-buy").disabled = !status.running;
  $("#paper-sell").disabled = !status.running;
  $("#paper-initial-cash").textContent = money(status.paper_account?.initial_cash);
  $("#paper-total-assets").textContent = money(status.paper_account?.total_available_assets);
  $("#paper-cash").textContent = money(status.paper_account?.cash_balance);
}

async function refreshTraderStatus() {
  try { renderTraderStatus(await api("/trader/status")); }
  catch (error) { $("#trader-status").textContent = error.message; }
}

function renderPaperPositions(positions = []) {
  const container = $("#paper-positions");
  if (!positions.length) { container.textContent = "모의 보유 종목이 없습니다."; return; }
  container.innerHTML = positions.map((position) => `<div><strong>${escapeHtml(position.stock_code)}</strong><span>${number(position.quantity)}주 · 평균 ${money(position.average_cost)} · 평가 ${money(position.market_value)}</span></div>`).join("");
}

async function loadPaperPositions() {
  try { renderPaperPositions((await api("/paper-positions")).positions); }
  catch (error) { $("#paper-positions").textContent = error.message; }
}

async function submitPaperOrder(side) {
  const stockCode = $("#paper-stock-code").value.trim().toUpperCase();
  const quantity = Number($("#paper-quantity").value);
  const result = $("#paper-order-result");
  result.textContent = "모의 주문을 처리하는 중입니다.";
  try {
    const payload = await api("/paper-orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ side, stock_code: stockCode, quantity }) });
    $("#paper-cash").textContent = money(payload.paper_account.cash_balance);
    $("#paper-total-assets").textContent = money(payload.paper_account.total_available_assets);
    renderPaperPositions(payload.positions);
    await loadDailyPerformance();
    result.textContent = `모의 ${payload.order.side === "BUY" ? "매수" : "매도"} 완료: ${payload.order.stock_code} ${payload.order.quantity}주 · ${money(payload.order.execution_price)}`;
  } catch (error) { result.textContent = error.message; }
}

$("#trader-start").addEventListener("click", async () => {
  try { renderTraderStatus(await api("/trader/start", { method: "POST" })); }
  catch (error) { $("#trader-status").textContent = error.message; }
});
$("#trader-stop").addEventListener("click", async () => {
  try { renderTraderStatus(await api("/trader/stop", { method: "POST" })); }
  catch (error) { $("#trader-status").textContent = error.message; }
});
$("#paper-buy").addEventListener("click", () => submitPaperOrder("BUY"));
$("#paper-sell").addEventListener("click", () => submitPaperOrder("SELL"));
loadHealth(); loadAccounts();
refreshTraderStatus();
loadPaperPositions();
loadDailyPerformance();
