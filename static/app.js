// Shared front-end helpers.
const INR = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

if (window.Chart) {
  Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
  Chart.defaults.color = "#5e6675";
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
}
const PALETTE = ["#14213d", "#f2a65a", "#3a86ff", "#2a9d8f", "#a8521a", "#8e9ab5"];

// Revenue history + forecast line chart.
function forecastChart(canvasId, f) {
  const el = document.getElementById(canvasId);
  if (!el || !f || !f.ready) return;
  const labels = f.history_labels.concat(f.forecast_labels);
  const hist = f.history_values.concat(f.forecast_values.map(() => null));
  // Join the forecast line to the last actual point.
  const fc = f.history_values.map((v, i) => (i === f.history_values.length - 1 ? v : null)).concat(f.forecast_values);
  new Chart(el, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Actual revenue", data: hist, borderColor: "#14213d", backgroundColor: "rgba(20,33,61,.08)", fill: true, tension: .3, pointRadius: 0, borderWidth: 2 },
        { label: "AI forecast", data: fc, borderColor: "#f2a65a", borderDash: [6, 4], tension: .3, pointRadius: 2, borderWidth: 2.5 },
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { tooltip: { callbacks: { label: (c) => c.raw == null ? null : `${c.dataset.label}: ${INR.format(c.raw)}` } } },
      scales: { y: { ticks: { callback: (v) => INR.format(v) }, grid: { color: "#ece9e0" } }, x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } } },
    },
  });
}

function doughnutChart(canvasId, labels, values) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  new Chart(el, {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: PALETTE, borderWidth: 2, borderColor: "#fffefb" }] },
    options: { maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "bottom" },
      tooltip: { callbacks: { label: (c) => `${c.label}: ${INR.format(c.raw)}` } } } },
  });
}

function barChart(canvasId, labels, values, label, money) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  new Chart(el, {
    type: "bar",
    data: { labels, datasets: [{ label, data: values, backgroundColor: "#f2a65a", borderRadius: 6 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: money ? { callback: (v) => INR.format(v) } : {}, grid: { color: "#ece9e0" } }, x: { grid: { display: false } } } },
  });
}

// New-sale form: add/remove lines and show a live total.
function initSaleForm() {
  const form = document.getElementById("sale-form");
  if (!form) return;
  const lines = document.getElementById("lines");
  const template = lines.querySelector(".line-item");

  function recalc() {
    let total = 0;
    lines.querySelectorAll(".line-item").forEach((li) => {
      const opt = li.querySelector("select").selectedOptions[0];
      const qtyInput = li.querySelector("input[name=quantity]");
      const price = opt ? parseFloat(opt.dataset.price || 0) : 0;
      const stock = opt ? parseInt(opt.dataset.stock || 0, 10) : 0;
      const qty = parseInt(qtyInput.value || 0, 10);
      qtyInput.max = stock || "";
      const line = price * qty;
      li.querySelector(".price").textContent = price ? INR.format(price) : "—";
      li.querySelector(".stock").textContent = opt && opt.value ? `${stock} in stock` : "";
      li.querySelector(".stock").classList.toggle("text-danger", qty > stock);
      li.querySelector(".line-total").textContent = INR.format(line);
      total += line;
    });
    document.getElementById("grand-total").textContent = INR.format(total);
  }

  document.getElementById("add-line").addEventListener("click", () => {
    const clone = template.cloneNode(true);
    clone.querySelector("select").value = "";
    clone.querySelector("input[name=quantity]").value = 1;
    lines.appendChild(clone);
    recalc();
  });
  lines.addEventListener("click", (e) => {
    if (e.target.closest(".remove") && lines.children.length > 1) {
      e.target.closest(".line-item").remove();
      recalc();
    }
  });
  lines.addEventListener("input", recalc);
  lines.addEventListener("change", recalc);
  recalc();
}
document.addEventListener("DOMContentLoaded", initSaleForm);
