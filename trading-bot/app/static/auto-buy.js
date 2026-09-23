const connectionDot = document.querySelector("#connection-dot");
const connectionText = document.querySelector("#connection-text");
const form = document.querySelector("#auto-buy-form");
const startButton = document.querySelector("#auto-buy-start");
const stopButton = document.querySelector("#auto-buy-stop");
const message = document.querySelector("#auto-buy-message");
const badge = document.querySelector("#auto-buy-badge");

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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  startButton.disabled = true;
  try {
    const status = await request("/auto-buy/start", {
      method: "POST",
      body: JSON.stringify({
        stock_code: document.querySelector("#auto-buy-code").value.trim(),
        quantity: Number(document.querySelector("#auto-buy-quantity").value),
      }),
    });
    renderStatus(status);
  } catch (error) {
    message.textContent = error.message;
    await loadStatus();
  }
});

stopButton.addEventListener("click", async () => {
  try {
    renderStatus(await request("/auto-buy/stop", { method: "POST" }));
  } catch (error) {
    message.textContent = error.message;
  }
});

loadStatus();
setInterval(loadStatus, 5000);
