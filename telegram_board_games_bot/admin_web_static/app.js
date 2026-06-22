const state = {
  token: sessionStorage.getItem("kyzma_admin_token") || "",
  overview: null,
  groups: [],
  users: [],
  selectedGroup: null,
  selectedUserId: null,
  messageTarget: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  if (state.token) authenticate();
});

function bindEvents() {
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.token = $("#token-input").value.trim();
    await authenticate();
  });
  $("#logout-button").addEventListener("click", logout);
  $("#refresh-button").addEventListener("click", refreshCurrentTab);
  $("#activity-refresh").addEventListener("click", loadActivity);
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  $("#group-search").addEventListener("input", debounce(loadGroups, 220));
  $("#user-search").addEventListener("input", debounce(loadUsers, 220));
  $("#broadcast-button").addEventListener("click", () => openMessageDialog({ all: true }));
  $("#group-message-button").addEventListener("click", () => openMessageDialog({ group: state.selectedGroup }));
  $("#group-back-button").addEventListener("click", () => $(".detail-pane").classList.remove("mobile-open"));
  $("#message-close").addEventListener("click", closeMessageDialog);
  $("#message-cancel").addEventListener("click", closeMessageDialog);
  $("#message-text").addEventListener("input", () => {
    $("#message-length").textContent = $("#message-text").value.length;
  });
  $("#message-form").addEventListener("submit", sendAdminMessage);
}

async function authenticate() {
  $("#login-error").hidden = true;
  try {
    state.overview = await api("/api/overview");
    sessionStorage.setItem("kyzma_admin_token", state.token);
    $("#login-view").hidden = true;
    $("#app").hidden = false;
    renderOverview();
    await Promise.all([loadGroups(), loadUsers()]);
  } catch (error) {
    $("#login-error").textContent = error.message;
    $("#login-error").hidden = false;
    state.token = "";
  }
}

function logout() {
  sessionStorage.removeItem("kyzma_admin_token");
  state.token = "";
  $("#app").hidden = true;
  $("#login-view").hidden = false;
  $("#token-input").value = "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${state.token}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    sessionStorage.removeItem("kyzma_admin_token");
    throw new Error("The admin token is invalid.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* no JSON body */ }
    throw new Error(detail);
  }
  return response.json();
}

function renderOverview() {
  const metrics = [
    [state.overview.users, "Users"],
    [state.overview.active_groups, "Active groups"],
    [state.overview.groups, "Known groups"],
    [state.overview.active_games, "Active games"],
    [state.overview.games, "Total games"],
    [state.overview.coin_supply, "Kyzma-coins"],
  ];
  $("#overview").innerHTML = metrics.map(([value, label]) =>
    `<div class="metric"><strong>${number(value)}</strong><span>${escapeHtml(label)}</span></div>`
  ).join("");
}

async function refreshCurrentTab() {
  state.overview = await api("/api/overview");
  renderOverview();
  const active = $(".tab.active").dataset.tab;
  if (active === "groups") await loadGroups();
  if (active === "users") await loadUsers();
  if (active === "activity") await loadActivity();
  showToast("Data refreshed");
}

function activateTab(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `${name}-tab`));
  if (name === "activity") loadActivity();
}

async function loadGroups() {
  const query = $("#group-search").value.trim();
  $("#group-list").innerHTML = '<div class="loading">Loading groups…</div>';
  try {
    state.groups = await api(`/api/groups${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    $("#group-count").textContent = `${state.groups.length} shown`;
    renderGroups();
  } catch (error) {
    $("#group-list").innerHTML = `<div class="empty-list">${escapeHtml(error.message)}</div>`;
  }
}

function renderGroups() {
  if (!state.groups.length) {
    $("#group-list").innerHTML = '<div class="empty-list">No groups found.</div>';
    return;
  }
  $("#group-list").innerHTML = state.groups.map((group) => `
    <button class="entity-row ${state.selectedGroup?.chat_id === group.chat_id ? "active" : ""}" data-chat-id="${group.chat_id}" type="button">
      <span><strong>${escapeHtml(group.title)}</strong><small>${group.chat_id}</small></span>
      <span class="counts"><span class="state ${group.is_active ? "" : "inactive"}">${group.is_active ? "Active" : "Inactive"}</span><br>${group.games_count} games · ${group.players_count} players</span>
    </button>
  `).join("");
  $$("#group-list .entity-row").forEach((row) => row.addEventListener("click", () => {
    const group = state.groups.find((candidate) => candidate.chat_id === Number(row.dataset.chatId));
    selectGroup(group);
  }));
}

async function selectGroup(group) {
  state.selectedGroup = group;
  renderGroups();
  $("#group-empty").hidden = true;
  $("#group-detail").hidden = false;
  $("#group-title").textContent = group.title;
  $("#group-meta").textContent = `${group.chat_id} · ${group.kind} · ${group.is_active ? "active" : "inactive"}`;
  $("#group-events").innerHTML = '<div class="loading">Loading activity…</div>';
  $(".detail-pane").classList.add("mobile-open");
  const events = await api(`/api/groups/${group.chat_id}/events?limit=150`);
  renderEvents($("#group-events"), events, false);
}

async function loadUsers() {
  const query = $("#user-search").value.trim();
  $("#users-table").innerHTML = '<tr><td colspan="6" class="loading">Loading users…</td></tr>';
  try {
    state.users = await api(`/api/users?limit=200${query ? `&q=${encodeURIComponent(query)}` : ""}`);
    $("#user-count").textContent = `${state.users.length} shown`;
    renderUsers();
  } catch (error) {
    $("#users-table").innerHTML = `<tr><td colspan="6" class="empty-list">${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderUsers() {
  $("#users-table").innerHTML = state.users.map((user) => `
    <tr data-user-id="${user.user_id}" class="${state.selectedUserId === user.user_id ? "active" : ""}">
      <td class="player-cell"><strong>${escapeHtml(user.display_name)}</strong><span>${user.username ? `@${escapeHtml(user.username)}` : "No username"}</span></td>
      <td>${user.user_id}</td><td>${number(user.balance)}</td><td>${user.draughts_rating}</td><td>${user.chess_rating}</td><td>${user.global_games}</td>
    </tr>
  `).join("") || '<tr><td colspan="6" class="empty-list">No users found.</td></tr>';
  $$("#users-table tr[data-user-id]").forEach((row) => row.addEventListener("click", () => selectUser(Number(row.dataset.userId))));
}

async function selectUser(userId) {
  state.selectedUserId = userId;
  renderUsers();
  const detail = await api(`/api/users/${userId}`);
  renderUserDetail(detail);
}

function renderUserDetail(user) {
  const globalStats = user.global_stats.map((stats) => `
    <div class="stats-row"><strong>${capitalize(stats.game_kind)} · ${stats.rating}</strong><span>${stats.games_played} games · ${stats.wins}W / ${stats.losses}L / ${stats.draws}D · best streak ${stats.best_streak}</span></div>
  `).join("") || '<p class="muted">No global games.</p>';
  const localStats = user.local_stats.map((stats) => `
    <div class="stats-row"><strong>${escapeHtml(stats.chat_title)} · ${capitalize(stats.game_kind)}</strong><span>${stats.rating} rating · ${stats.games_played} games · ${stats.wins}W / ${stats.losses}L / ${stats.draws}D</span></div>
  `).join("") || '<p class="muted">No local stats.</p>';
  const coins = user.coin_events.slice(0, 12).map((event) => `
    <div class="coin-row"><strong class="${event.amount >= 0 ? "amount-positive" : "amount-negative"}">${event.amount >= 0 ? "+" : ""}${event.amount} coins</strong><span>${formatReason(event.reason)} · ${formatDate(event.created_at)}</span></div>
  `).join("") || '<p class="muted">No coin events.</p>';
  $("#user-detail").innerHTML = `
    <button id="user-detail-close" class="mobile-back" type="button" aria-label="Close player profile" title="Close player profile">←</button>
    <div class="profile-heading"><div class="eyebrow">Player profile</div><h2>${escapeHtml(user.display_name)}</h2><p class="muted">${user.user_id}${user.username ? ` · @${escapeHtml(user.username)}` : ""}</p></div>
    <div class="stat-grid"><div class="stat-cell"><strong>${number(user.balance)}</strong><span>Kyzma-coins</span></div><div class="stat-cell"><strong>${user.language_code || "—"}</strong><span>Language</span></div></div>
    <section class="detail-section"><h3>Global stats</h3>${globalStats}</section>
    <section class="detail-section"><h3>Group stats</h3>${localStats}</section>
    <section class="detail-section"><h3>Recent wallet activity</h3>${coins}</section>
  `;
  $("#user-detail").hidden = false;
  $("#user-detail-close").addEventListener("click", () => {
    $("#user-detail").hidden = true;
    state.selectedUserId = null;
    renderUsers();
  });
}

async function loadActivity() {
  $("#activity-events").innerHTML = '<div class="loading">Loading activity…</div>';
  const events = await api("/api/activity?limit=200");
  renderEvents($("#activity-events"), events, true);
}

function renderEvents(container, events, showContext) {
  if (!events.length) {
    container.innerHTML = '<div class="empty-list">No activity recorded yet.</div>';
    return;
  }
  container.innerHTML = events.map((event) => {
    const formatted = formatEvent(event);
    const context = showContext && (event.chat_title || event.chat_id !== null)
      ? `<p class="context">${escapeHtml(event.chat_title || "Global / private")} · ${event.chat_id ?? "—"}</p>` : "";
    return `<article class="event"><time>${formatDate(event.occurred_at)}</time><div class="event-rail"><span class="event-dot ${formatted.kind}"></span></div><div class="event-body"><h3>${escapeHtml(formatted.title)}</h3><p>${escapeHtml(formatted.detail)}</p>${context}</div></article>`;
  }).join("");
}

function formatEvent(event) {
  if (event.type === "game_finished") {
    const mode = `${capitalize(event.game_kind)} · ${event.rated ? "rated" : "unrated"}`;
    if (event.winner_user_id) {
      const loserId = event.winner_user_id === event.black_user_id ? event.white_user_id : event.black_user_id;
      const loserName = event.winner_user_id === event.black_user_id ? event.white_name : event.black_name;
      return { kind: "game", title: `${event.winner_name} · ID ${event.winner_user_id} won`, detail: `${mode}. Defeated ${loserName} · ID ${loserId} (${event.reason || "finished"}).` };
    }
    return { kind: "game", title: "Game ended in a draw", detail: `${mode}. ${event.black_name} · ID ${event.black_user_id} vs ${event.white_name} · ID ${event.white_user_id} (${event.reason || "draw"}).` };
  }
  if (event.type === "coin_event") {
    const player = `${event.user_name} · ID ${event.user_id}`;
    if (event.reason === "daily_claim") return { kind: "coin", title: `${player} claimed the daily bonus`, detail: `+${event.amount} kyzma-coins.` };
    if (event.amount < 0) return { kind: "coin", title: `${player} paid ${Math.abs(event.amount)} coins`, detail: `${formatReason(event.reason)} · ${capitalize(event.game_kind)}.` };
    return { kind: "coin", title: `${player} earned ${event.amount} coins`, detail: `${formatReason(event.reason)}${event.multiplier ? ` · ×${event.multiplier}` : ""}.` };
  }
  if (event.type === "admin_message") return { kind: "admin", title: "Admin message sent", detail: event.details?.text || "Message sent." };
  if (event.type === "group_membership") return { kind: "admin", title: `Group marked ${event.details?.active ? "active" : "inactive"}`, detail: event.details?.title || "Membership changed." };
  return { kind: "admin", title: formatReason(event.type), detail: JSON.stringify(event.details || {}) };
}

function openMessageDialog(target) {
  state.messageTarget = target;
  $("#message-recipient").textContent = target.all ? "All active groups" : target.group.title;
  $("#message-text").value = "";
  $("#message-length").textContent = "0";
  $("#message-error").hidden = true;
  $("#message-dialog").showModal();
  $("#message-text").focus();
}

function closeMessageDialog() { $("#message-dialog").close(); }

async function sendAdminMessage(event) {
  event.preventDefault();
  const text = $("#message-text").value.trim();
  if (!text) return;
  $("#message-submit").disabled = true;
  $("#message-error").hidden = true;
  try {
    const payload = state.messageTarget.all
      ? { text, all_active_groups: true, chat_ids: [] }
      : { text, all_active_groups: false, chat_ids: [state.messageTarget.group.chat_id] };
    const result = await api("/api/messages", { method: "POST", body: JSON.stringify(payload) });
    closeMessageDialog();
    showToast(`Sent to ${result.sent.length}; failed: ${result.failed.length}`);
    if (state.selectedGroup) await selectGroup(state.selectedGroup);
  } catch (error) {
    $("#message-error").textContent = error.message;
    $("#message-error").hidden = false;
  } finally {
    $("#message-submit").disabled = false;
  }
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 3200);
}

function formatDate(value) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function formatReason(value) { return String(value || "event").replaceAll("_", " ").replaceAll(":", " · "); }
function capitalize(value) { const text = String(value || ""); return text.charAt(0).toUpperCase() + text.slice(1); }
function number(value) { return new Intl.NumberFormat().format(value || 0); }
function escapeHtml(value) { const node = document.createElement("span"); node.textContent = String(value ?? ""); return node.innerHTML; }
function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }
