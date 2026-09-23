const connectionDot = document.querySelector("#connection-dot");
const connectionText = document.querySelector("#connection-text");
const form = document.querySelector("#auto-buy-form");
const stockInput = document.querySelector("#auto-buy-code");
const tradeModeInput = document.querySelector("#auto-trade-mode");
const startButton = document.querySelector("#auto-buy-start");
const stopButton = document.querySelector("#auto-buy-stop");
const message = document.querySelector("#auto-buy-message");
const badge = document.querySelector("#auto-buy-badge");

stockInput.value = "삼성전자";
stockInput.placeholder = "예: 삼성전자 또는 005930";
document.querySelector('label[for="auto-buy-code"]').textContent = "회사명 또는 종목코드";
document.querySelector(".auto-buy-screen h1").innerHTML = "자동매매 <span>v0.1</span>";
document.querySelector(".auto-buy-notice span").textContent = "실제 토스증권 주문은 전송하지 않습니다. 매수 또는 매도 신호가 확인되면 모의 주문 1회 후 자동 정지합니다.";
document.querySelector(".auto-buy-layout h2").textContent = "자동매매 시작";
startButton.textContent = "자동매매 시작";
stopButton.textContent = "자동매매 정지";

const stateLabels = {
  IDLE: "대기",
  WATCHING: "감시 중",
  COMPLETED: "완료",
  STOPPED: "정지",
  ERROR: "오류",
};

function setConnection(connected) {
  connectionDot.parentElement.classList.toggle("connected", connected);
  connectionText.textContent = connected ? "API · DB 연결됨" : "연결을 확인하세요";
}

function renderStatus(status) {
  const running = Boolean(status.running);
  const label = stateLabels[status.state] || status.state || "대기";
  badge.textContent = label;
  badge.className = running ? "runtime-running" : "runtime-stopped";
  document.querySelector("#auto-buy-state").textContent = label;
  document.querySelector("#auto-buy-stock").textContent = status.stock_code || "-";
  document.querySelector("#auto-buy-amount").textContent = status.quantity ? `${status.quantity}주` : "-";
  document.querySelector("#auto-buy-signal").textContent = status.last_signal || "-";
  document.querySelector("#auto-buy-interval").textContent = `${status.interval_seconds || 60}초`;
  message.textContent = status.message || "자동매수 대기 중입니다.";
  startButton.disabled = running;
  stopButton.disabled = !running;
}

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "요청 처리에 실패했습니다.");
  return body;
}

const formatPrice = (value, currency) => new Intl.NumberFormat("ko-KR", {
  style: "currency", currency: currency || "KRW", maximumFractionDigits: 0,
}).format(Number(value));

function renderAutoChart(chart) {
  const currentPrice = Number(chart.current_price);
  const points = chart.points.map((point) => ({ timestamp: point.timestamp, value: Number(point.close_price) }))
    .filter((point) => Number.isFinite(point.value));
  const currentDate = String(chart.observed_at).slice(0, 10);
  const lastPoint = points.at(-1);
  if (lastPoint && String(lastPoint.timestamp).slice(0, 10) === currentDate) lastPoint.value = currentPrice;
  else if (Number.isFinite(currentPrice)) points.push({ timestamp: chart.observed_at, value: currentPrice });
  if (points.length < 2) throw new Error("차트 데이터가 부족합니다.");

  const width = 720, height = 260, left = 74, right = 24, top = 24, bottom = 36;
  const values = points.map((point) => point.value);
  const low = Math.min(...values), high = Math.max(...values);
  const spread = Math.max(high - low, Math.max(high * 0.01, 1));
  const min = low - spread * 0.15, max = high + spread * 0.15;
  const x = (index) => left + (index / (points.length - 1)) * (width - left - right);
  const y = (value) => top + ((max - value) / (max - min)) * (height - top - bottom);
  const line = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
  const grid = [0, 0.5, 1].map((ratio) => {
    const value = max - (max - min) * ratio, lineY = y(value).toFixed(1);
    return `<line x1="${left}" x2="${width - right}" y1="${lineY}" y2="${lineY}" class="chart-grid"/><text x="${left - 10}" y="${Number(lineY) + 4}" class="chart-axis">${Math.round(value).toLocaleString("ko-KR")}</text>`;
  }).join("");
  const labels = [0, Math.floor((points.length - 1) / 2), points.length - 1].map((index) => `<text x="${x(index)}" y="${height - 12}" text-anchor="middle" class="chart-axis">${String(points[index].timestamp).slice(5, 10)}</text>`).join("");
  const latest = points.at(-1);
  document.querySelector("#auto-price-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="auto-chart-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#4b90ff" stop-opacity=".35"/><stop offset="100%" stop-color="#4b90ff" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${line} L${x(points.length - 1)},${height - bottom} L${x(0)},${height - bottom} Z" fill="url(#auto-chart-fill)"/><path d="${line}" class="chart-line"/><circle cx="${x(points.length - 1)}" cy="${y(latest.value)}" r="5" class="chart-dot"/>${labels}</svg>`;
}

async function loadAutoChart(query = stockInput.value.trim()) {
  if (!query) return;
  try {
    const chart = await request(`/market/chart?symbol=${encodeURIComponent(query)}&count=30`);
    renderAutoChart(chart);
    document.querySelector("#auto-chart-title").textContent = `${chart.symbol} · ${chart.name || "-"} 가격 흐름`;
    document.querySelector("#auto-chart-price").textContent = formatPrice(chart.current_price, chart.currency);
    document.querySelector("#auto-chart-time").textContent = `현재가 ${String(chart.observed_at).replace("T", " ")}`;
    document.querySelector("#auto-chart-status").textContent = `${chart.refresh_seconds}초마다 현재가 갱신`;
    document.querySelector("#auto-chart-message").textContent = "자동매수 신호 판단과 별개인 참고용 가격 차트입니다.";
  } catch (error) {
    document.querySelector("#auto-chart-status").textContent = "조회 실패";
    document.querySelector("#auto-chart-message").textContent = error.message;
  }
}

async function loadStatus() {
  try {
    const [health, status] = await Promise.all([request("/health"), request("/auto-buy/status")]);
    setConnection(health.status === "ok");
    renderStatus(status);
  } catch (error) {
    setConnection(false);
    message.textContent = error.message;
  }
}

async function verifyTossConnection() {
  const button = document.querySelector("#connection-check");
  button.disabled = true;
  button.textContent = "확인 중";
  try {
    await request("/auth/verify", { method: "POST" });
    setConnection(true);
    connectionText.textContent = "토스 인증 연결됨";
  } catch (error) {
    setConnection(false);
    connectionText.textContent = "토스 연결 실패";
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "토스 연결 확인";
  }
}

async function resetPaperTrading() {
  if (!window.confirm("모의 잔고, 보유종목, 모의 주문과 거래기록을 모두 초기화할까요? 실제 토스 계좌에는 영향을 주지 않습니다.")) return;
  const button = document.querySelector("#paper-reset");
  button.disabled = true;
  try {
    const result = await request("/paper/reset", {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    });
    renderStatus(await request("/auto-buy/status"));
    message.textContent = result.message;
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  startButton.disabled = true;
  try {
    const status = await request("/auto-buy/start", {
      method: "POST",
      body: JSON.stringify({
        stock_code: stockInput.value.trim(),
        quantity: Number(document.querySelector("#auto-buy-quantity").value),
        trade_mode: tradeModeInput.value,
      }),
    });
    renderStatus(status);
    await loadAutoChart(status.stock_code);
  } catch (error) {
    await loadStatus();
    message.textContent = error.message;
  }
});

stopButton.addEventListener("click", async () => {
  try {
    renderStatus(await request("/auto-buy/stop", { method: "POST" }));
  } catch (error) {
    message.textContent = error.message;
  }
});

document.querySelector("#connection-check").addEventListener("click", verifyTossConnection);
document.querySelector("#paper-reset").addEventListener("click", resetPaperTrading);
let chartInputTimer;
stockInput.addEventListener("input", () => {
  clearTimeout(chartInputTimer);
  chartInputTimer = setTimeout(() => loadAutoChart(), 700);
});

loadStatus();
loadAutoChart();
setInterval(loadStatus, 5000);
setInterval(() => loadAutoChart(), 15000);
