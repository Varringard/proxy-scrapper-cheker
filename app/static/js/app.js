// ProxyPulse Frontend Controller
let ws = null;
let currentPage = 1;
const pageSize = 50;
let totalPages = 1;
let debounceTimer = null;
let activeTask = null;

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  initWebSocket();
  loadStats();
  loadProxies();
  loadSources();
  updateExportUrl();

  // Periodic stats refresh
  setInterval(loadStats, 4000);
});

// ─── WEBSOCKET & REALTIME LOGS ───────────────────────────────────────────────

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/ws`;
  
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    updateLiveIndicator(true, "Система активна");
    appendLog("WebSocket соединение установлено с ProxyPulse Core.");
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleWsEvent(msg.event, msg.data);
    } catch (e) {
      console.error("WS Parse error:", e);
    }
  };

  ws.onclose = () => {
    updateLiveIndicator(false, "Переподключение...");
    setTimeout(initWebSocket, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function handleWsEvent(event, data) {
  if (event === "scraper_start") {
    activeTask = "scraper";
    setTaskButtonsRunning(true);
    showProgress("Сбор прокси из источников...", 0);
    appendLog(`[Scraper] Запущен сбор. Источников в очереди: ${data.sources_total}`);
  } else if (event === "scraper_progress") {
    const pct = data.sources_total > 0 ? Math.round((data.sources_scraped / data.sources_total) * 100) : 0;
    showProgress(`Сбор: ${data.current_source || "обработка"} (${data.sources_scraped}/${data.sources_total})`, pct);
    appendLog(`[Scraper] ${data.current_source}: найдено всего ${data.total_found} (+${data.new_added} новых)`);
    loadStats();
  } else if (event === "scraper_done") {
    activeTask = null;
    setTaskButtonsRunning(false);
    hideProgress();
    appendLog(`[Scraper] Сбор завершен! Всего найдено: ${data.total_found}, новых добавлено: ${data.new_added}`);
    loadStats();
    loadProxies();
    loadSources();
  } else if (event === "checker_start") {
    activeTask = "checker";
    setTaskButtonsRunning(true);
    showProgress("Проверка прокси на доступность и скорость...", 0);
    appendLog(`[Checker] Запущена валидация пула. Прокси к проверке: ${data.total_to_check}`);
  } else if (event === "checker_progress") {
    const pct = data.total_to_check > 0 ? Math.round((data.checked / data.total_to_check) * 100) : 0;
    showProgress(`Проверено ${data.checked}/${data.total_to_check} (Живых: ${data.alive}, Скорость: ${data.checks_per_second}/с)`, pct);
    if (data.last_result) {
      const r = data.last_result;
      const statusStr = r.alive ? `✓ ЖИВОЙ (${r.latency}ms, ${r.anonymity}, ${r.country_code})` : `✗ DEAD`;
      appendLog(`[Check] ${r.protocol.toUpperCase()} ${r.ip}:${r.port} -> ${statusStr}`);
    }
    loadStats();
  } else if (event === "checker_done") {
    activeTask = null;
    setTaskButtonsRunning(false);
    hideProgress();
    appendLog(`[Checker] Проверка завершена! Проверено: ${data.checked}, живых: ${data.alive}, мертвых: ${data.dead}`);
    loadStats();
    loadProxies();
  } else if (event === "scraper_stopped" || event === "checker_stopped") {
    activeTask = null;
    setTaskButtonsRunning(false);
    hideProgress();
    appendLog("[System] Задача остановлена пользователем.");
    loadStats();
  }
}

function updateLiveIndicator(active, text) {
  const badge = document.getElementById("live-indicator");
  const label = document.getElementById("live-text");
  if (label) label.textContent = text;
  if (!active) {
    badge.style.borderColor = "rgba(244, 63, 94, 0.4)";
    badge.style.color = "var(--accent-rose)";
  } else {
    badge.style.borderColor = "rgba(16, 185, 129, 0.3)";
    badge.style.color = "var(--accent-emerald)";
  }
}

function appendLog(text) {
  const terminal = document.getElementById("terminal-logs");
  if (!terminal) return;
  const time = new Date().toLocaleTimeString();
  const line = document.createElement("div");
  line.className = "terminal-line";
  line.innerHTML = `<span class="time">[${time}]</span> ${escapeHtml(text)}`;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}

function clearTerminal() {
  const terminal = document.getElementById("terminal-logs");
  if (terminal) terminal.innerHTML = "";
}

function showProgress(taskName, percent) {
  const card = document.getElementById("task-progress-card");
  const nameEl = document.getElementById("progress-task-name");
  const statsEl = document.getElementById("progress-task-stats");
  const fillEl = document.getElementById("progress-bar-fill");
  if (card) card.style.display = "block";
  if (nameEl) nameEl.textContent = taskName;
  if (statsEl) statsEl.textContent = `${percent}%`;
  if (fillEl) fillEl.style.width = `${percent}%`;
}

function hideProgress() {
  const card = document.getElementById("task-progress-card");
  if (card) card.style.display = "none";
}

function setTaskButtonsRunning(running) {
  const scrapeBtn = document.getElementById("btn-start-scrape");
  const checkBtn = document.getElementById("btn-check-all");
  const checkNewBtn = document.getElementById("btn-check-new");
  const stopBtn = document.getElementById("btn-stop-all");
  
  if (scrapeBtn) scrapeBtn.disabled = running;
  if (checkBtn) checkBtn.disabled = running;
  if (checkNewBtn) checkNewBtn.disabled = running;
  if (stopBtn) stopBtn.disabled = !running;
}

// ─── TABS ────────────────────────────────────────────────────────────────────

function switchTab(tabId) {
  document.querySelectorAll(".tab-content").forEach(el => el.style.display = "none");
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
  
  const target = document.getElementById(tabId);
  if (target) target.style.display = "block";

  const btn = document.querySelector(`[data-tab='${tabId}']`);
  if (btn) btn.classList.add("active");

  if (tabId === "tab-proxies") reloadProxies();
  if (tabId === "tab-sources") loadSources();
}

// ─── STATS & DASHBOARD ───────────────────────────────────────────────────────

async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("stat-total").textContent = data.total.toLocaleString();
    document.getElementById("stat-unchecked").textContent = `Непроверено: ${data.unchecked.toLocaleString()}`;
    document.getElementById("stat-alive").textContent = data.alive.toLocaleString();
    document.getElementById("stat-dead").textContent = data.dead.toLocaleString();
    document.getElementById("stat-latency").textContent = `${data.avg_latency || 0} ms`;

    const totalChecked = data.alive + data.dead;
    const alivePct = totalChecked > 0 ? Math.round((data.alive / totalChecked) * 100) : 0;
    document.getElementById("stat-alive-pct").textContent = `${alivePct}% от проверенных`;

    document.getElementById("tab-proxies-count").textContent = data.alive.toLocaleString();

    // Render Protocols
    const protoContainer = document.getElementById("protocols-list");
    if (protoContainer) {
      if (!data.protocols || data.protocols.length === 0) {
        protoContainer.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">Нет данных</div>`;
      } else {
        protoContainer.innerHTML = data.protocols.map(p => {
          const pct = data.total > 0 ? Math.round((p.count / data.total) * 100) : 0;
          return `
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                <span class="badge badge-${p.protocol}">${p.protocol.toUpperCase()}</span>
                <span style="color: var(--text-muted);"><b style="color: var(--accent-emerald);">${p.alive_count || 0}</b> живых / ${p.count} всего (${pct}%)</span>
              </div>
              <div class="progress-bar-bg" style="height: 6px;">
                <div class="progress-bar-fill" style="width: ${pct}%;"></div>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    // Render Anonymity
    const anonContainer = document.getElementById("anonymity-list");
    if (anonContainer) {
      if (!data.anonymity || data.anonymity.length === 0) {
        anonContainer.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">Пока нет проверенных живых прокси</div>`;
      } else {
        anonContainer.innerHTML = data.anonymity.map(a => {
          const count = a.count;
          const pct = data.alive > 0 ? Math.round((count / data.alive) * 100) : 0;
          return `
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
                <span class="badge badge-${a.anonymity === 'elite' ? 'elite' : a.anonymity === 'transparent' ? 'trans' : 'anon'}">${(a.anonymity || 'unknown').toUpperCase()}</span>
                <span><b>${count}</b> (${pct}%)</span>
              </div>
              <div class="progress-bar-bg" style="height: 6px;">
                <div class="progress-bar-fill" style="width: ${pct}%; background: var(--accent-emerald);"></div>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    // Render Countries
    const countryContainer = document.getElementById("countries-list");
    if (countryContainer) {
      if (!data.top_countries || data.top_countries.length === 0) {
        countryContainer.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">Данные геолокации обрабатываются...</div>`;
      } else {
        countryContainer.innerHTML = data.top_countries.map(c => {
          const flag = getFlagEmoji(c.country_code);
          return `
            <div style="display: flex; align-items: center; justify-content: space-between; font-size: 13px; padding: 4px 0;">
              <span>${flag} <b>${escapeHtml(c.country_name || c.country_code)}</b> (${c.country_code})</span>
              <span class="badge" style="background: var(--bg-input);">${c.count} прокси</span>
            </div>
          `;
        }).join("");
      }
    }

    // Sync button state
    if (data.scraper_running || data.checker_running) {
      setTaskButtonsRunning(true);
    }

  } catch (e) {
    console.error("Load stats error:", e);
  }
}

// ─── ACTIONS ─────────────────────────────────────────────────────────────────

async function startScraper() {
  try {
    const res = await fetch("/api/scraper/start", { method: "POST" });
    const data = await res.json();
    if (data.status === "error") {
      alert(data.message);
    }
  } catch (e) {
    alert("Ошибка запуска скрапера: " + e);
  }
}

async function startChecker(onlyUnchecked = false) {
  try {
    const res = await fetch(`/api/checker/start?only_unchecked=${onlyUnchecked}`, { method: "POST" });
    const data = await res.json();
    if (data.status === "error") {
      alert(data.message);
    }
  } catch (e) {
    alert("Ошибка запуска чекера: " + e);
  }
}

async function stopAll() {
  try {
    await fetch("/api/scraper/stop", { method: "POST" });
    await fetch("/api/checker/stop", { method: "POST" });
    setTaskButtonsRunning(false);
    hideProgress();
  } catch (e) {
    console.error("Stop error:", e);
  }
}

async function purgeDeadProxies() {
  if (!confirm("Удалить все недоступные (Dead) прокси из базы?")) return;
  try {
    const res = await fetch("/api/proxies/dead", { method: "DELETE" });
    const data = await res.json();
    appendLog(`[System] Удалено мертвых узлов: ${data.deleted}`);
    loadStats();
    loadProxies();
  } catch (e) {
    alert("Ошибка удаления: " + e);
  }
}

// ─── PROXIES TABLE ───────────────────────────────────────────────────────────

function debounceReloadProxies() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    currentPage = 1;
    loadProxies();
  }, 350);
}

function reloadProxies() {
  currentPage = 1;
  loadProxies();
}

async function loadProxies() {
  const search = document.getElementById("filter-search")?.value || "";
  const status = document.getElementById("filter-status")?.value || "";
  const proto = document.getElementById("filter-protocol")?.value || "";
  const anon = document.getElementById("filter-anonymity")?.value || "";
  const sort = document.getElementById("filter-sort")?.value || "latency-asc";

  const [sort_by, sort_order] = sort.split("-");

  const params = new URLSearchParams({
    page: currentPage,
    limit: pageSize,
    sort_by: sort_by || "latency",
    sort_order: sort_order || "asc"
  });

  if (search) params.append("search", search);
  if (proto) params.append("protocol", proto);
  if (anon) params.append("anonymity", anon);
  if (status === "1" || status === "0") params.append("alive", status);

  try {
    const res = await fetch(`/api/proxies?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();

    totalPages = data.pages || 1;
    renderProxiesTable(data.items);
    updatePagination(data.total, data.page, totalPages);
  } catch (e) {
    console.error("Load proxies error:", e);
  }
}

function renderProxiesTable(items) {
  const tbody = document.getElementById("proxy-table-body");
  if (!tbody) return;

  if (!items || items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 40px;">
          Прокси не найдены по заданным критериям
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = items.map(p => {
    const protoBadge = `<span class="badge badge-${p.protocol}">${p.protocol.toUpperCase()}</span>`;
    
    // Status & Latency
    let statusBadge = `<span class="badge badge-pending">Не проверен</span>`;
    let latencyBadge = `<span style="color: var(--text-muted);">-</span>`;
    if (p.last_checked_at) {
      if (p.alive) {
        statusBadge = `<span class="badge badge-online">Живой</span>`;
        const latClass = p.latency < 500 ? "latency-fast" : p.latency < 1500 ? "latency-med" : "latency-slow";
        latencyBadge = `<span class="${latClass}">${p.latency} ms</span>`;
      } else {
        statusBadge = `<span class="badge badge-offline">Dead</span>`;
      }
    }

    // Anonymity
    let anonBadge = `<span style="color: var(--text-muted);">-</span>`;
    if (p.anonymity && p.anonymity !== "unknown" && p.anonymity !== "dead") {
      const bClass = p.anonymity === "elite" ? "badge-elite" : p.anonymity === "transparent" ? "badge-trans" : "badge-anon";
      anonBadge = `<span class="badge ${bClass}">${p.anonymity.toUpperCase()}</span>`;
    }

    const flag = getFlagEmoji(p.country_code);
    const countryText = p.country_name || p.country_code || "Unknown";
    const locStr = `${flag} ${escapeHtml(countryText)}${p.city ? ', ' + escapeHtml(p.city) : ''}`;
    const timeStr = p.last_checked_at ? new Date(p.last_checked_at).toLocaleTimeString() : "-";
    const proxyFull = `${p.ip}:${p.port}`;

    return `
      <tr id="proxy-row-${p.id}">
        <td>${protoBadge}</td>
        <td>
          <b style="font-family: monospace; font-size: 13px;">${escapeHtml(proxyFull)}</b>
          <button class="btn btn-secondary" style="padding: 2px 6px; font-size: 11px; margin-left: 6px;" onclick="copyToClipboard('${proxyFull}')" title="Копировать IP:Port">📋</button>
        </td>
        <td>${locStr}</td>
        <td>${latencyBadge}</td>
        <td>${anonBadge}</td>
        <td>${statusBadge}</td>
        <td style="color: var(--text-muted); font-size: 12px;">${timeStr}</td>
        <td style="text-align: right;">
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;" id="check-btn-${p.id}" onclick="checkOneProxy(${p.id})">🔍 Тест</button>
          <button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="deleteProxy(${p.id})">✕</button>
        </td>
      </tr>
    `;
  }).join("");
}

function updatePagination(total, page, pages) {
  const infoEl = document.getElementById("pagination-info");
  const prevBtn = document.getElementById("page-prev-btn");
  const nextBtn = document.getElementById("page-next-btn");
  const currentEl = document.getElementById("page-current");

  if (infoEl) infoEl.textContent = `Всего: ${total.toLocaleString()} прокси · Страница ${page} из ${pages}`;
  if (currentEl) currentEl.textContent = page;
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= pages;
}

function changePage(delta) {
  const newPage = currentPage + delta;
  if (newPage >= 1 && newPage <= totalPages) {
    currentPage = newPage;
    loadProxies();
  }
}

async function checkOneProxy(id) {
  const btn = document.getElementById(`check-btn-${id}`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳...";
  }
  try {
    const res = await fetch(`/api/proxies/check-one/${id}`, { method: "POST" });
    const r = await res.json();
    appendLog(`[Single Check] ${r.protocol.toUpperCase()} ${r.ip}:${r.port} -> ${r.alive ? `✓ ЖИВОЙ (${r.latency}ms)` : '✗ DEAD'}`);
    loadProxies();
    loadStats();
  } catch (e) {
    alert("Ошибка проверки: " + e);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "🔍 Тест";
    }
  }
}

async function deleteProxy(id) {
  if (!confirm("Удалить этот прокси?")) return;
  try {
    await fetch(`/api/proxies/${id}`, { method: "DELETE" });
    loadProxies();
    loadStats();
  } catch (e) {
    console.error("Delete error:", e);
  }
}

// ─── ROTATING GATEWAY ────────────────────────────────────────────────────────

async function updateGatewayConfig() {
  const strategy = document.getElementById("gateway-strategy")?.value;
  const country = document.getElementById("gateway-country")?.value;
  try {
    await fetch("/api/gateway/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy, country })
    });
    appendLog(`[Gateway] Конфигурация обновлена: Стратегия=${strategy}, Страна=${country || 'Любая'}`);
  } catch (e) {
    console.error("Gateway config error:", e);
  }
}

async function testGatewayConnection() {
  const resBox = document.getElementById("gateway-test-result");
  if (resBox) {
    resBox.style.display = "block";
    resBox.innerHTML = `<span>⏳ Отправка тестового запроса через <b>http://localhost:8081</b>...</span>`;
  }
  try {
    const res = await fetch("/api/gateway/test");
    const data = await res.json();
    if (data.status === "success") {
      resBox.innerHTML = `
        <div style="color: var(--accent-emerald); font-weight: 600; margin-bottom: 4px;">✓ Тест успешен! Шлюз работает превосходно.</div>
        <div style="font-size: 13px;">Исходящий IP: <b>${escapeHtml(data.outgoing_ip)}</b> | Пинг туннеля: <b>${data.latency_ms} ms</b></div>
      `;
    } else {
      resBox.innerHTML = `<div style="color: var(--accent-rose); font-weight: 600;">✗ ${escapeHtml(data.message)}</div>`;
    }
  } catch (e) {
    if (resBox) resBox.innerHTML = `<div style="color: var(--accent-rose);">Ошибка подключения к шлюзу: ${e}</div>`;
  }
}

// ─── SOURCES ─────────────────────────────────────────────────────────────────

async function loadSources() {
  try {
    const res = await fetch("/api/sources");
    if (!res.ok) return;
    const sources = await res.json();
    
    document.getElementById("tab-sources-count").textContent = sources.length;
    const tbody = document.getElementById("sources-table-body");
    if (!tbody) return;

    tbody.innerHTML = sources.map(s => {
      const checkedAttr = s.enabled ? "checked" : "";
      const lastStr = s.last_scraped_at ? new Date(s.last_scraped_at).toLocaleString() : "Еще не собирался";
      return `
        <tr>
          <td>
            <input type="checkbox" ${checkedAttr} onchange="toggleSource(${s.id})">
          </td>
          <td><b>${escapeHtml(s.name)}</b></td>
          <td><span class="badge badge-${s.protocol}">${s.protocol.toUpperCase()}</span></td>
          <td style="font-family: monospace; font-size: 11px; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            <a href="${escapeHtml(s.url)}" target="_blank" style="color: var(--accent-cyan); text-decoration: none;">${escapeHtml(s.url)}</a>
          </td>
          <td><b>${(s.proxies_found || 0).toLocaleString()}</b></td>
          <td style="color: var(--text-muted); font-size: 12px;">${lastStr}</td>
          <td style="text-align: right;">
            <button class="btn btn-danger" style="padding: 2px 6px; font-size: 11px;" onclick="deleteSource(${s.id})">✕</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (e) {
    console.error("Load sources error:", e);
  }
}

async function toggleSource(id) {
  try {
    await fetch(`/api/sources/${id}/toggle`, { method: "PATCH" });
  } catch (e) {
    console.error("Toggle source error:", e);
  }
}

async function deleteSource(id) {
  if (!confirm("Удалить этот источник?")) return;
  try {
    await fetch(`/api/sources/${id}`, { method: "DELETE" });
    loadSources();
  } catch (e) {
    console.error("Delete source error:", e);
  }
}

async function addCustomSource() {
  const name = document.getElementById("new-source-name")?.value.trim();
  const url = document.getElementById("new-source-url")?.value.trim();
  const proto = document.getElementById("new-source-proto")?.value;

  if (!name || !url) {
    alert("Пожалуйста, заполните название и URL источника");
    return;
  }

  try {
    const res = await fetch("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, url, protocol: proto })
    });
    if (res.ok) {
      document.getElementById("new-source-name").value = "";
      document.getElementById("new-source-url").value = "";
      loadSources();
      appendLog(`[Sources] Добавлен новый источник: ${name}`);
    } else {
      const err = await res.json();
      alert("Ошибка: " + err.detail);
    }
  } catch (e) {
    alert("Ошибка: " + e);
  }
}

// ─── IMPORT / EXPORT ─────────────────────────────────────────────────────────

async function importProxies() {
  const text = document.getElementById("import-textarea")?.value.trim();
  const defaultProto = document.getElementById("import-default-proto")?.value || "http";
  const resultDiv = document.getElementById("import-result");

  if (!text) {
    alert("Вставьте текст со списком прокси");
    return;
  }

  if (resultDiv) resultDiv.innerHTML = "<span>⏳ Обработка и импорт...</span>";

  try {
    const res = await fetch("/api/proxies/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, default_protocol: defaultProto })
    });
    const data = await res.json();
    if (data.status === "success") {
      resultDiv.innerHTML = `<span style="color: var(--accent-emerald);">✓ Успешно распознано: ${data.found}, добавлено новых: <b>${data.added}</b>!</span>`;
      document.getElementById("import-textarea").value = "";
      loadStats();
      loadProxies();
      appendLog(`[Import] Ручной импорт: распознано ${data.found}, новых ${data.added}`);
    } else {
      resultDiv.innerHTML = `<span style="color: var(--accent-amber);">${escapeHtml(data.message)}</span>`;
    }
  } catch (e) {
    if (resultDiv) resultDiv.innerHTML = `<span style="color: var(--accent-rose);">Ошибка: ${e}</span>`;
  }
}

function updateExportUrl() {
  const format = document.getElementById("export-format")?.value || "txt";
  const proto = document.getElementById("export-proto")?.value || "";
  const alive = document.getElementById("export-alive")?.value || "";
  const withProto = document.getElementById("export-with-proto")?.checked || false;

  const params = new URLSearchParams({ format });
  if (proto) params.append("protocol", proto);
  if (alive) params.append("alive", alive);
  if (withProto) params.append("with_protocol", "true");

  const url = `${window.location.origin}/api/export?${params.toString()}`;
  const el = document.getElementById("export-api-url");
  if (el) el.textContent = url;
  return url;
}

function downloadExport() {
  const url = updateExportUrl();
  window.open(url, "_blank");
}

function copyExportApiUrl() {
  const url = updateExportUrl();
  copyToClipboard(url);
  alert("Прямая ссылка на API скопирована в буфер обмена!");
}

// ─── UTILITIES ───────────────────────────────────────────────────────────────

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).catch(err => {
    console.error("Clipboard copy error:", err);
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getFlagEmoji(countryCode) {
  if (!countryCode || countryCode === "XX" || countryCode.length !== 2) return "🌐";
  const codePoints = countryCode
    .toUpperCase()
    .split("")
    .map(char => 127397 + char.charCodeAt(0));
  return String.fromCodePoint(...codePoints);
}
