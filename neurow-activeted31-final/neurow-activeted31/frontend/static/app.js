const form = document.querySelector("#contact-form");
const result = document.querySelector("#form-result");
const statusBadge = document.querySelector("#api-status");

async function updateHealth() {
  try {
    const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
    const data = await response.json();
    statusBadge.textContent = data.status === "ok" ? "API online" : "API degraded";
  } catch {
    statusBadge.textContent = "API offline";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  result.classList.remove("error");

  if (!form.reportValidity()) return;

  const button = form.querySelector("button");
  const payload = Object.fromEntries(new FormData(form).entries());
  button.disabled = true;
  button.textContent = "Отправляем…";
  result.textContent = "";

  try {
    const response = await fetch("/api/contact", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": crypto.randomUUID(),
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      const retry = data?.error?.details?.retry_after;
      throw new Error(
        retry
          ? `${data.error.message} Повторите через ${retry} сек.`
          : data?.error?.message || "Не удалось отправить обращение",
      );
    }
    result.textContent = `${data.message}. Номер: ${data.request_id}`;
    form.reset();
  } catch (error) {
    result.classList.add("error");
    result.textContent = error.message || "Сервис временно недоступен";
  } finally {
    button.disabled = false;
    button.textContent = "Отправить обращение";
  }
});

updateHealth();
