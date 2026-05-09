/**
 * ForcedFocus Chrome Extension — Popup Logic
 * Controls session start/stop, displays timer, and manages UI state.
 */

const API = "http://127.0.0.1:7070";
let mode = "blacklist";
let duration = 120;
let countdown = null;
let totalSecs = 0;
let currentRemaining = 0; // P1: Track for drift guard

let sessionType = "standard";
let pomoFocusMin = 25;
let pomoBreakMin = 5;
let pomoCycles = 4;
let selectedGroups = new Set();
let availableGroups = {};

let apiToken = ""; // A2: Per-launch API token for mutation auth

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ── Toast (R8: replaces alert() which is blocked in extension popups) ────────

function showError(msg) {
  const existing = document.querySelector(".popup-toast");
  if (existing) existing.remove();
  const el = document.createElement("div");
  el.className = "popup-toast";
  el.textContent = msg;
  el.style.cssText =
    "position:fixed;top:8px;left:8px;right:8px;padding:10px;background:rgba(239,68,68,0.95);color:white;border-radius:12px;font-size:12px;font-weight:500;z-index:999;text-align:center;backdrop-filter:blur(8px);box-shadow:0 4px 16px rgba(0,0,0,0.3);animation:fadeIn 0.2s ease;";
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 0.3s";
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

// ── API (A2: with token auth + 401 auto-retry) ──────────────────────────────

async function loadApiToken() {
  try {
    const res = await fetch(API + "/api/token", {
      signal: AbortSignal.timeout(2000),
    });
    const data = await res.json();
    if (data.token) apiToken = data.token;
  } catch (e) {
    console.error("[ForcedFocus] Token load failed:", e);
  }
}

async function api(method, path, body = null) {
  const headers = { "Content-Type": "application/json" };
  if (method !== "GET" && apiToken) {
    headers["X-API-Token"] = apiToken;
  }
  const opts = {
    method,
    headers,
    signal: AbortSignal.timeout(5000),
  };
  if (body) opts.body = JSON.stringify(body);

  try {
    const res = await fetch(API + path, opts);
    // A2: Auto-refresh token on 401 (daemon restarted)
    if (res.status === 401 && method !== "GET") {
      await loadApiToken();
      headers["X-API-Token"] = apiToken;
      const retry = await fetch(API + path, {
        method,
        headers,
        body: opts.body,
      });
      return await retry.json();
    }
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  } catch (err) {
    console.error("[ForcedFocus] API error:", err.message);
    return { status: "error", message: "Server unreachable." };
  }
}

async function checkServer() {
  try {
    const res = await fetch(API + "/api/status", {
      signal: AbortSignal.timeout(2000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Timer (P1: wall-clock anchor + R4: no negative values) ──────────────────

function fmt(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function updateRing(remaining) {
  const circ = 2 * Math.PI * 52; // 326.73
  const progress = totalSecs > 0 ? 1 - remaining / totalSecs : 0;
  const ringProgress = $("#ringProgress");
  if (ringProgress) {
    ringProgress.style.strokeDashoffset = circ * (1 - progress);
  }
}

function startCountdown(secs) {
  // P1: Don't restart if already counting and values are close
  if (countdown && Math.abs(currentRemaining - secs) <= 2) return;
  if (countdown) clearInterval(countdown);

  const anchor = performance.now();
  const anchorSecs = secs;
  currentRemaining = secs;

  const timerValue = $("#timerValue");
  const timerLabel = $("#timerLabel");

  if (timerValue) timerValue.textContent = fmt(currentRemaining);
  if (timerLabel) timerLabel.textContent = "REMAINING";
  updateRing(currentRemaining);

  countdown = setInterval(() => {
    const elapsed = (performance.now() - anchor) / 1000;
    currentRemaining = Math.max(0, Math.round(anchorSecs - elapsed));

    if (timerValue) timerValue.textContent = fmt(currentRemaining);
    updateRing(currentRemaining);

    if (currentRemaining <= 0) {
      clearInterval(countdown);
      countdown = null;
      refresh();
    }
  }, 250); // P1: Higher frequency, lower visual drift
}

async function fetchGroups() {
  try {
    const res = await api("GET", "/api/groups");
    if (res.groups) {
      availableGroups = res.groups;
      renderGroups();
    }
  } catch (e) {
    console.error("[ForcedFocus] Group load failed:", e);
  }
}

function renderGroups() {
  const grid = $("#groupGrid");
  const section = $("#groupSection");
  const countLabel = $("#groupCount");

  if (!grid || !section) return;

  const names = Object.keys(availableGroups);
  if (names.length === 0) {
    section.classList.add("hidden");
    return;
  }

  section.classList.remove("hidden");
  grid.textContent = "";

  names.forEach((name) => {
    const chip = document.createElement("div");
    chip.className = "group-chip" + (selectedGroups.has(name) ? " active" : "");
    chip.textContent = name;
    chip.onclick = () => {
      if (selectedGroups.has(name)) {
        selectedGroups.delete(name);
      } else {
        selectedGroups.add(name);
      }
      renderGroups();
    };
    grid.appendChild(chip);
  });

  if (countLabel) {
    countLabel.textContent = `${selectedGroups.size} selected`;
  }
}

function stopCountdown() {
  if (countdown) {
    clearInterval(countdown);
    countdown = null;
  }
  currentRemaining = 0;

  const timerValue = $("#timerValue");
  const timerLabel = $("#timerLabel");
  const ringProgress = $("#ringProgress");

  if (timerValue) timerValue.textContent = "00:00";
  if (timerLabel) timerLabel.textContent = "READY";
  if (ringProgress) ringProgress.style.strokeDashoffset = 326.73;
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStatus(data) {
  const active = data.active;
  const badge = $("#badge");

  // Badge
  if (badge) {
    badge.textContent = active
      ? data.session_type === "rescue"
        ? "RESCUE"
        : data.mode.toUpperCase()
      : "Idle";
    badge.classList.toggle("active", active);
  }

  // Controls visibility
  const idleControls = $("#idleControls");
  const activeControls = $("#activeControls");
  const stopDialog = $("#stopDialog");

  if (idleControls) idleControls.classList.toggle("hidden", active);
  if (activeControls) activeControls.classList.toggle("hidden", !active);

  const intentDisplay = $("#activeIntentDisplay");

  if (active) {
    const intentContainer = $("#activeIntentContainer");
    if (intentContainer) {
      if (data.intent) {
        intentContainer.style.display = "block";
        if (intentDisplay) {
          intentDisplay.textContent = data.intent;
        }
        const intentTasksContainer = $("#activeIntentTasks");
        if (intentTasksContainer) {
          renderIntentTasks(intentTasksContainer, data.intent_tasks || []);
        }
      } else {
        intentContainer.style.display = "none";
      }
    }
  }
  if (stopDialog) stopDialog.classList.add("hidden");

  if (active) {
    if (data.session_type === "pomodoro") {
      totalSecs = data.pomo_phase_total || 1;
      startCountdown(data.pomo_phase_remaining || 0);

      const infoType = $("#infoType");
      if (infoType) infoType.textContent = "Pomodoro";

      const pomoPhaseRow = $("#pomoPhaseRow");
      const pomoCycleRow = $("#pomoCycleRow");
      if (pomoPhaseRow) pomoPhaseRow.style.display = "flex";
      if (pomoCycleRow) pomoCycleRow.style.display = "flex";

      // R1: Safe DOM construction instead of innerHTML for phase dot
      const infoPhase = $("#infoPhase");
      if (infoPhase) {
        infoPhase.textContent = "";
        const dot = document.createElement("span");
        dot.className = `phase-dot ${data.pomo_phase === "break" ? "break" : "focus"}`;
        infoPhase.appendChild(dot);
        infoPhase.appendChild(
          document.createTextNode(" " + String(data.pomo_phase).toUpperCase()),
        );
      }

      // Update ring color
      const ring = $("#ringProgress");
      if (ring) ring.classList.toggle("break", data.pomo_phase === "break");

      const infoCycle = $("#infoCycle");
      if (infoCycle)
        infoCycle.textContent = `${data.pomo_current_cycle}/${data.pomo_total_cycles}`;

      const pomoNextRow = $("#pomoNextRow");
      const infoPomoNext = $("#infoPomoNext");
      if (data.pomo_phase_expiry_time) {
        if (pomoNextRow) pomoNextRow.style.display = "flex";
        if (infoPomoNext)
          infoPomoNext.textContent = `${data.pomo_phase_expiry_time}`;
      } else {
        if (pomoNextRow) pomoNextRow.style.display = "none";
      }

      const timerRing = $(".timer-ring");
      const timerLabel = $("#timerLabel");
      if (data.pomo_phase === "break") {
        if (timerRing) timerRing.classList.add("break");
        if (timerLabel) timerLabel.textContent = "BREAK";
      } else {
        if (timerRing) timerRing.classList.remove("break");
        if (timerLabel) timerLabel.textContent = "FOCUS";
      }
    } else {
      totalSecs = data.total_duration_seconds || data.remaining_seconds;
      startCountdown(data.remaining_seconds);

      const infoType = $("#infoType");
      if (infoType) infoType.textContent = "Standard";

      const pomoPhaseRow = $("#pomoPhaseRow");
      const pomoCycleRow = $("#pomoCycleRow");
      const pomoNextRow = $("#pomoNextRow");
      if (pomoPhaseRow) pomoPhaseRow.style.display = "none";
      if (pomoCycleRow) pomoCycleRow.style.display = "none";
      if (pomoNextRow) pomoNextRow.style.display = "none";

      const timerRing = $(".timer-ring");
      if (timerRing) timerRing.classList.remove("break");
      const ring = $("#ringProgress");
      if (ring) ring.classList.remove("break");
    }

    // Session info
    const infoMode = $("#infoMode");
    if (infoMode) {
      infoMode.textContent =
        data.session_type === "rescue" ? "Rescue Throne 🛡️" : data.mode;
    }

    const infoExpires = $("#infoExpires");
    if (infoExpires) infoExpires.textContent = data.expires_at;

    // Unlock info
    const unlockRow = $("#unlockRow");
    const infoUnlock = $("#infoUnlock");
    if (data.pending_unlock) {
      if (unlockRow) unlockRow.style.display = "flex";
      if (infoUnlock) infoUnlock.textContent = data.pending_unlock;
    } else {
      if (unlockRow) unlockRow.style.display = "none";
    }
  } else {
    totalSecs = 0;
    stopCountdown();
    const timerRing = $(".timer-ring");
    if (timerRing) timerRing.classList.remove("break");
    const ring = $("#ringProgress");
    if (ring) ring.classList.remove("break");
  }
}

// ── Intent Tasks ─────────────────────────────────────────────────────────────

function renderIntentTasks(container, tasks) {
  if (!tasks || tasks.length === 0) {
    container.innerHTML = "";
    return;
  }
  
  const ul = document.createElement("ul");
  ul.dir = "auto";
  ul.style.listStyle = "none";
  ul.style.padding = "0";
  ul.style.margin = "0";
  ul.style.display = "flex";
  ul.style.flexDirection = "column";
  ul.style.gap = "8px";
  ul.style.width = "100%";
  
  tasks.forEach((task, index) => {
    const li = document.createElement("li");
    li.dir = "auto";
    li.className = "intent-task-item";
    li.style.display = "flex";
    li.style.alignItems = "flex-start";
    li.style.gap = "8px";
    li.style.margin = "1px 0";
    li.style.width = "100%";
    li.style.boxSizing = "border-box";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "custom-checkbox";
    checkbox.checked = task.completed;
    
    checkbox.addEventListener("change", async (e) => {
      task.completed = e.target.checked;
      label.style.textDecoration = task.completed ? "line-through" : "none";
      label.style.opacity = task.completed ? "0.5" : "1";
      
      try {
        await api("POST", "/api/intent", { 
          intent: $("#activeIntentDisplay").textContent, 
          intent_tasks: tasks 
        });
      } catch (err) {
        console.error("Failed to update task status", err);
      }
    });
    
    const label = document.createElement("label");
    label.dir = "auto";
    label.textContent = task.text;
    label.style.cursor = "pointer";
    label.style.flex = "1";
    label.style.lineHeight = "1.4";
    label.style.textDecoration = task.completed ? "line-through" : "none";
    label.style.opacity = task.completed ? "0.5" : "1";
    
    label.addEventListener("click", (e) => {
      e.preventDefault();
      checkbox.click();
    });
    
    li.appendChild(checkbox);
    li.appendChild(label);
    ul.appendChild(li);
  });
  
  container.innerHTML = "";
  container.appendChild(ul);
}

async function refresh() {
  try {
    const data = await api("GET", "/api/status");
    if (data.status === "ok") {
      renderStatus(data);
    }
  } catch (error) {
    console.error("Failed to refresh status:", error);
  }
}

// ── Events ───────────────────────────────────────────────────────────────────

function initEvents() {
  // Mode chips
  $$(".mode-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".mode-chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      mode = btn.dataset.mode;
    });
  });

  // Session Type chips
  $$(".type-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".type-chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      sessionType = btn.dataset.type;

      const standardControls = $("#standardControls");
      const pomoControls = $("#pomoControls");

      if (sessionType === "pomodoro") {
        if (standardControls) standardControls.classList.add("hidden");
        if (pomoControls) pomoControls.classList.remove("hidden");
        updatePomoSummary();
      } else {
        if (standardControls) standardControls.classList.remove("hidden");
        if (pomoControls) pomoControls.classList.add("hidden");
      }
    });
  });

  // Duration chips
  $$(".dur-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".dur-chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      duration = parseInt(btn.dataset.min);
      const customMin = $("#customMin");
      if (customMin) customMin.value = "";
    });
  });

  // Custom minutes input
  const customMin = $("#customMin");
  if (customMin) {
    customMin.addEventListener("input", () => {
      const val = parseInt(customMin.value);
      if (val > 0) {
        $$(".dur-chip").forEach((b) => b.classList.remove("active"));
        duration = val;
      }
    });
  }

  // Pomodoro chips & inputs
  function updatePomoSummary() {
    const pomoFocus = $("#pomoFocus");
    const pomoBreak = $("#pomoBreak");
    const pomoCyclesInput = $("#pomoCycles");
    const pomoTotal = $("#pomoTotal");

    if (pomoFocus) pomoFocusMin = parseInt(pomoFocus.value) || 25;
    if (pomoBreak) pomoBreakMin = parseInt(pomoBreak.value) || 5;
    if (pomoCyclesInput) pomoCycles = parseInt(pomoCyclesInput.value) || 4;

    const total = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    const h = Math.floor(total / 60);
    const m = total % 60;

    if (pomoTotal) {
      pomoTotal.textContent = `Total: ${h}h ${String(m).padStart(2, "0")}m`;
    }
  }

  $$(".pomo-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".pomo-chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const pomoFocus = $("#pomoFocus");
      const pomoBreak = $("#pomoBreak");
      if (pomoFocus) pomoFocus.value = btn.dataset.focus;
      if (pomoBreak) pomoBreak.value = btn.dataset.break;
      updatePomoSummary();
    });
  });

  ["#pomoFocus", "#pomoBreak", "#pomoCycles"].forEach((selector) => {
    const element = $(selector);
    if (element) {
      element.addEventListener("input", () => {
        $$(".pomo-chip").forEach((b) => b.classList.remove("active"));
        updatePomoSummary();
      });
    }
  });

  // Start — Shows Intent Dialog
  const btnStart = $("#btnStart");
  if (btnStart) {
    btnStart.addEventListener("click", () => {
      const intentDialog = $("#intentDialog");
      const intentInput = $("#intentDialogInput");
      if (intentDialog) {
        intentDialog.classList.remove("hidden");
        if (intentInput) {
          intentInput.value = "";
          const intentTasksInput = $("#intentTasksInput");
          if (intentTasksInput) intentTasksInput.value = "";
          intentInput.focus();
        }
      }
    });
  }

  // Cancel Intent Dialog
  const btnCancelIntent = $("#btnCancelIntent");
  if (btnCancelIntent) {
    btnCancelIntent.addEventListener("click", () => {
      const intentDialog = $("#intentDialog");
      if (intentDialog) intentDialog.classList.add("hidden");
    });
  }

  // Confirm Intent & Start Session
  const btnConfirmIntent = $("#btnConfirmIntent");
  if (btnConfirmIntent) {
    btnConfirmIntent.addEventListener("click", async () => {
      const intentDialog = $("#intentDialog");
      const intentInput = $("#intentDialogInput");
      if (intentDialog) intentDialog.classList.add("hidden");

      btnStart.textContent = "⏳ Starting...";
      btnStart.disabled = true;

      let payload = {};
      const intentVal = intentInput ? intentInput.value.trim() : "";
      
      const intentTasksInput = $("#intentTasksInput");
      const intentTasksRaw = intentTasksInput ? intentTasksInput.value.trim() : "";
      const intentTasks = intentTasksRaw
        .split("\n")
        .map(t => t.trim().replace(/^[-*•]\s*/, "").trim())
        .filter(t => t.length > 0)
        .map(t => ({ text: t, completed: false }));

      if (sessionType === "pomodoro") {
        const totalMin = (pomoFocusMin + pomoBreakMin) * pomoCycles;
        totalSecs = totalMin * 60;
        payload = {
          duration: totalMin,
          mode: mode,
          session_type: "pomodoro",
          focus_minutes: pomoFocusMin,
          break_minutes: pomoBreakMin,
          cycles: pomoCycles,
          groups: Array.from(selectedGroups),
        };
      } else {
        totalSecs = duration * 60;
        payload = {
          duration,
          mode,
          session_type: "standard",
          groups: Array.from(selectedGroups),
        };
      }

      if (intentVal) {
        payload.intent = intentVal;
      }
      if (intentTasks.length > 0) {
        payload.intent_tasks = intentTasks;
      }

      try {
        const res = await api("POST", "/api/start", payload);
        if (res.status === "ok") {
          await refresh();
        } else {
          showError(res.message || "Failed to start session.");
        }
      } catch (error) {
        showError(`Failed to start session: ${error.message}`);
      } finally {
        btnStart.textContent = "▶ Start Blocking";
        btnStart.disabled = false;
      }
    });
  }

  // Rescue — R6: disable button during async
  const btnRescue = $("#btnRescue");
  if (btnRescue) {
    btnRescue.addEventListener("click", async () => {
      btnRescue.textContent = "⏳ Activating...";
      btnRescue.disabled = true;

      const rescueDuration = $("#rescueDuration");
      const dur = rescueDuration
        ? parseInt(rescueDuration.value, 10) || 10
        : 10;

      const payload = {
        duration: dur,
        mode: "whitelist",
        session_type: "rescue",
      };

      try {
        const res = await api("POST", "/api/start", payload);
        if (res.status === "ok") {
          await refresh();
        } else {
          showError(res.message || "Failed to activate rescue.");
        }
      } catch (error) {
        showError(`Failed to activate rescue: ${error.message}`);
      } finally {
        btnRescue.textContent = "⚡ Activate Rescue";
        btnRescue.disabled = false;
      }
    });
  }

  // Stop → show dialog
  const btnStop = $("#btnStop");
  if (btnStop) {
    btnStop.addEventListener("click", () => {
      const stopDialog = $("#stopDialog");
      const passInput = $("#passInput");
      const errMsg = $("#errMsg");
      if (stopDialog) stopDialog.classList.remove("hidden");
      if (passInput) {
        passInput.value = "";
        passInput.focus();
      }
      if (errMsg) errMsg.classList.add("hidden");
    });
  }

  // Cancel
  const btnCancel = $("#btnCancel");
  if (btnCancel) {
    btnCancel.addEventListener("click", () => {
      const stopDialog = $("#stopDialog");
      if (stopDialog) stopDialog.classList.add("hidden");
    });
  }

  // Confirm unlock — R6: disable button during async
  const btnConfirm = $("#btnConfirm");
  if (btnConfirm) {
    btnConfirm.addEventListener("click", async () => {
      const passInput = $("#passInput");
      const errMsg = $("#errMsg");
      const key = passInput ? passInput.value : "";

      if (!key) {
        if (errMsg) {
          errMsg.textContent = "Enter passphrase.";
          errMsg.classList.remove("hidden");
        }
        return;
      }

      btnConfirm.disabled = true;
      btnConfirm.textContent = "⏳...";
      try {
        const res = await api("POST", "/api/stop", { key });
        if (res.status === "pending" || res.status === "ok") {
          const stopDialog = $("#stopDialog");
          if (stopDialog) stopDialog.classList.add("hidden");
          await refresh();
        } else {
          if (errMsg) {
            errMsg.textContent = res.message || "Invalid passphrase.";
            errMsg.classList.remove("hidden");
          }
        }
      } catch (error) {
        if (errMsg) {
          errMsg.textContent = `Connection error: ${error.message}`;
          errMsg.classList.remove("hidden");
        }
      } finally {
        btnConfirm.textContent = "Unlock";
        btnConfirm.disabled = false;
      }
    });
  }

  // Enter key in passphrase
  const passInput = $("#passInput");
  if (passInput) {
    passInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const btnConfirm = $("#btnConfirm");
        if (btnConfirm) btnConfirm.click();
      }
    });
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  const offline = $("#offline");
  const main = $("#main");

  const online = await checkServer();
  if (!online) {
    if (offline) offline.classList.remove("hidden");
    if (main) main.classList.add("hidden");
    return;
  }

  if (offline) offline.classList.add("hidden");
  if (main) main.classList.remove("hidden");

  // A2: Load auth token before any mutations
  await loadApiToken();

  // Fetch groups for idle selection
  await fetchGroups();

  initEvents();


  // S3: Listen for phase change broadcasts from background worker
  // Triggers immediate UI refresh when Pomodoro transitions focus↔break
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === "phaseChanged") {
      refresh();
    }
  });

  // S1: Fetch status FIRST, then render — eliminates 00:00 flash on popup open
  await refresh();

  // Poll every 2s
  setInterval(refresh, 2000);
}

document.addEventListener("DOMContentLoaded", init);
