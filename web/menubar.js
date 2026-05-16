const API = "http://127.0.0.1:7070";
let currentMode = "blacklist";
let currentType = "standard";
let totalSecs = 0;
let currentRemaining = 0;
let countdownInterval = null;
let apiToken = "";
let selectedGroups = [];
let availableGroups = {};

const AudioManager = {
  settings: {},
  _current: null,
  play: function (type) {
    const file = this.settings[`sound_${type}`];
    if (!file) return;
    if (this._current) {
      this._current.pause();
      this._current = null;
    }
    this._current = new Audio("/sounds/" + encodeURIComponent(file));
    this._current.play().catch((e) => console.log("Audio error:", e));
  },
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
  badge: $("#mbBadge"),
  badgeText: $(".status-text"),
  activeState: $("#activeState"),
  idleState: $("#idleState"),
  progress: $("#mbProgress"),
  time: $("#mbTime"),
  label: $("#mbLabel"),

  // Info Grid
  infoMode: $("#mbInfoMode"),
  infoType: $("#mbInfoType"),
  infoExpires: $("#mbInfoExpires"),
  infoNext: $("#mbInfoNext"),
  infoNextTime: $("#mbInfoNextTime"),
  nextRow: $("#mbNextRow"),

  btnStart: $("#mbBtnStart"),
  btnStop: $("#mbBtnStop"),
  mbBtnRescue: $("#mbBtnRescue"),
  rescueDur: $("#rescueDur"),

  // Switchers
  modeChips: $$(".mode-chip"),
  typeChips: $$(".type-chip"),
  durChips: $$(".dur-chip"),
  pomoChips: $$(".pomo-chip"),

  // Sections
  standardSection: $("#standardSection"),
  pomoSection: $("#pomoSection"),

  // Inputs
  customMin: $("#customMin"),
  pomoFocus: $("#pomoFocus"),
  pomoBreak: $("#pomoBreak"),
  pomoCycles: $("#pomoCycles"),
  // Intent UI
  intentState: $("#intentState"),
  intentPromptInput: $("#intentPromptInput"),
  btnIntentCancel: $("#btnIntentCancel"),
  btnIntentConfirm: $("#btnIntentConfirm"),

  // Group UI
  groupSection: $("#groupSection"),
  groupGrid: $("#groupGrid"),
  groupCount: $("#groupCount"),
};

const activeRequests = new Map();

async function api(method, path, body = null) {
  const headers = { "Content-Type": "application/json" };
  if (method !== "GET" && apiToken) headers["X-API-Token"] = apiToken;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  // Flow Reliability: Prevent GET request race conditions and overlap
  let requestKey = method + ":" + (path || "");
  if (method === "GET") {
    if (activeRequests.has(requestKey)) {
      activeRequests.get(requestKey).abort();
    }
    const controller = new AbortController();
    opts.signal = controller.signal;
    activeRequests.set(requestKey, controller);
  }
  try {
    const res = await fetch(API + path, opts);
    // S4: Auto-refresh token on 401 (daemon restarted)
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
    const data = await res.json();
    if (method === "GET") activeRequests.delete(requestKey);
    return data;
  } catch (err) {
    if (err.name === "AbortError") return new Promise(() => {});
    return { status: "error", message: "Offline" };
  }
}

async function loadApiToken() {
  try {
    const res = await fetch(API + "/api/token");
    const data = await res.json();
    if (data.token) apiToken = data.token;
  } catch (e) {
    console.error("Token load failed:", e);
  }
}

function fmt(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0)
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function fmtClock(secs) {
  const now = new Date();
  const future = new Date(now.getTime() + secs * 1000);
  let h = future.getHours();
  const m = future.getMinutes();
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12;
  h = h ? h : 12; // the hour '0' should be '12'
  return `${h}:${String(m).padStart(2, "0")} ${ampm}`;
}

function updateRing(remMs, isInitial = false) {
  const circ = 565.48; // 2 * Math.PI * 90
  const totalMs = totalSecs * 1000;
  // Fill the ring clockwise as time passes
  const prog = totalMs > 0 ? 1 - remMs / totalMs : 0;

  if (isInitial) els.progress.style.transition = "none";
  els.progress.style.strokeDasharray = `${Math.max(0, Math.min(1, prog)) * circ} ${circ}`;
  els.progress.style.strokeDashoffset = 0;
  if (isInitial) {
    els.progress.offsetHeight; // force reflow
    els.progress.style.transition = "";
  }
}

function startCountdown(rem) {
  if (countdownInterval && Math.abs(currentRemaining - rem) <= 2) return;
  if (countdownInterval) clearInterval(countdownInterval);

  currentRemaining = rem;
  const startTime = Date.now();
  const durationMs = rem * 1000;
  const endTime = startTime + durationMs;

  let isFirst = true;
  const tick = () => {
    const now = Date.now();
    const remMs = endTime - now;

    if (remMs <= 0) {
      clearInterval(countdownInterval);
      countdownInterval = null;
      els.time.textContent = fmt(0);
      updateRing(0);
      refresh();
      return;
    }

    const remSecs = Math.ceil(remMs / 1000);
    currentRemaining = remSecs; // Update global state for drift guard comparison
    els.time.textContent = fmt(remSecs);
    if (els.infoNextTime) els.infoNextTime.textContent = fmtClock(remSecs);

    updateRing(remMs, isFirst);
    isFirst = false;
  };

  tick();
  countdownInterval = setInterval(tick, 16); // 60fps for buttery smooth movement
}

let isStarting = false;

function renderStatus(data) {
  if (isStarting) return; // Prevent UI jank while daemon applies kernel rules

  const active = data.active;
  const schedules = data.schedules || [];
  const hasSchedules = schedules.length > 0;
  const isPrimaryScheduled = !active && hasSchedules;
  const isIntentVisible = !els.intentState.classList.contains("hidden");

  if (active || isPrimaryScheduled) {
    els.idleState.classList.add("hidden");
    els.intentState.classList.add("hidden");
    els.activeState.classList.remove("hidden");

    if (active) {
      // Populate Info Grid
      els.infoMode.textContent =
        data.session_type === "rescue" ? "RESCUE" : data.mode.toUpperCase();
      els.infoType.textContent = data.session_type.toUpperCase();
      els.infoExpires.textContent = data.expires_at || "--:--";

      els.badgeText.textContent =
        data.session_type === "rescue" ? "RESCUE" : "ACTIVE";
      els.badge.classList.add("active");

      if (data.session_type === "pomodoro") {
        totalSecs = data.pomo_phase_total || 1;
        startCountdown(data.pomo_phase_remaining || 0);
        els.label.textContent = data.pomo_phase.toUpperCase();

        els.nextRow.classList.remove("hidden");
        els.infoNext.textContent =
          data.pomo_phase === "focus" ? "BREAK" : "FOCUS";

        if (data.pomo_phase === "break") {
          $(".timer-ring").classList.add("break");
        } else {
          $(".timer-ring").classList.remove("break");
        }
      } else {
        totalSecs = data.total_duration_seconds || data.remaining_seconds;
        startCountdown(data.remaining_seconds);
        els.label.textContent = "REMAINING";
        els.nextRow.classList.add("hidden");
        $(".timer-ring").classList.remove("break");
      }
      
      const intentContainer = document.getElementById("activeIntentContainer");
      const intentDisplay = document.getElementById("activeIntentDisplay");
      
      if (intentContainer && intentDisplay) {
        if (data.intent) {
          intentContainer.classList.remove("hidden");
          intentDisplay.textContent = data.intent;
          
          const intentTasksContainer = document.getElementById("activeIntentTasks");
          if (intentTasksContainer) {
            renderIntentTasks(intentTasksContainer, data.intent_tasks || []);
          }
        } else {
          intentContainer.classList.add("hidden");
        }
      }
    } else {
      // Primary Scheduled
      const nextSch = schedules[0];
      const startMs = new Date(nextSch.start_time_iso).getTime();
      const secs = Math.max(0, Math.floor((startMs - Date.now()) / 1000));
      
      els.infoMode.textContent = nextSch.mode.toUpperCase();
      els.infoType.textContent = "SCHEDULED";
      els.infoExpires.textContent = nextSch.starts_at;
      
      els.badgeText.textContent = "SCHEDULED";
      els.badge.classList.add("active");
      
      totalSecs = 0;
      startCountdown(secs);
      els.label.textContent = "STARTING IN";
      els.nextRow.classList.add("hidden");
      $(".timer-ring").classList.remove("break");
      
      const intentContainer = document.getElementById("activeIntentContainer");
      if (intentContainer) intentContainer.classList.add("hidden");
    }
  } else {
    // We are idle
    if (!isIntentVisible) {
      els.idleState.classList.remove("hidden");
      els.activeState.classList.add("hidden");
      els.intentState.classList.add("hidden");
    }
    els.badgeText.textContent = "Idle";
    els.badge.classList.remove("active");
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
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
          intent: document.getElementById("activeIntentDisplay").textContent, 
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

async function fetchGroups() {
  try {
    const res = await api("GET", "/api/groups");
    if (res.groups) {
      availableGroups = res.groups;
      renderGroups();
    }
  } catch (e) {
    console.error("Failed to fetch groups:", e);
  }
}

function renderGroups() {
  if (!els.groupGrid || !els.groupSection) return;

  const names = Object.keys(availableGroups);
  if (names.length === 0) {
    els.groupSection.classList.add("hidden");
    return;
  }

  els.groupSection.classList.remove("hidden");
  els.groupGrid.innerHTML = "";

  names.forEach((name) => {
    const chip = document.createElement("div");
    chip.className =
      "group-chip" + (selectedGroups.includes(name) ? " active" : "");
    chip.textContent = name;
    chip.onclick = () => {
      if (selectedGroups.includes(name)) {
        selectedGroups = selectedGroups.filter((g) => g !== name);
      } else {
        selectedGroups.push(name);
      }
      renderGroups();
    };
    els.groupGrid.appendChild(chip);
  });

  if (els.groupCount) {
    els.groupCount.textContent = `${selectedGroups.length} selected`;
  }
}

async function refresh() {
  const data = await api("GET", "/api/status");
  if (data.status === "ok") {
    renderStatus(data);
  } else {
    els.badgeText.textContent = "Offline";
    els.badge.classList.remove("active");
  }
}

function initEvents() {
  // Mode switcher
  els.modeChips.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.modeChips.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentMode = btn.dataset.mode;
    });
  });

  // Type switcher
  els.typeChips.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.typeChips.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentType = btn.dataset.type;

      if (currentType === "pomodoro") {
        els.standardSection.classList.add("hidden");
        els.pomoSection.classList.remove("hidden");
      } else {
        els.standardSection.classList.remove("hidden");
        els.pomoSection.classList.add("hidden");
      }
    });
  });

  // Duration chips
  els.durChips.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.durChips.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      els.customMin.value = "";
    });
  });

  els.customMin.addEventListener("input", () => {
    els.durChips.forEach((b) => b.classList.remove("active"));
  });

  // Pomodoro chips
  els.pomoChips.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.pomoChips.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      els.pomoFocus.value = btn.dataset.focus;
      els.pomoBreak.value = btn.dataset.break;
    });
  });

  els.btnStart.addEventListener("click", () => {
    els.idleState.classList.add("hidden");
    els.intentState.classList.remove("hidden");
    els.intentPromptInput.value = "";
    const intentTasksInput = document.getElementById("intentTasksInput");
    if (intentTasksInput) intentTasksInput.value = "";
    els.intentPromptInput.focus();
  });

  els.btnIntentCancel.addEventListener("click", () => {
    els.intentState.classList.add("hidden");
    els.idleState.classList.remove("hidden");
  });
  
  els.intentPromptInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      els.btnIntentConfirm.click();
    }
  });

  els.btnIntentConfirm.addEventListener("click", async () => {
    const originalIntentHTML = els.btnIntentConfirm.innerHTML;
    els.btnIntentConfirm.innerHTML = '<span class="btn-spinner"></span> Starting...';
    els.btnIntentConfirm.disabled = true;
    els.btnIntentConfirm.setAttribute("aria-busy", "true");
    isStarting = true;

    let payload = {
      mode: currentMode,
      session_type: currentType,
      groups: selectedGroups,
    };
    
    const intentStr = els.intentPromptInput.value.trim();
    if (intentStr) {
      payload.intent = intentStr;
    }
    
    const intentTasksInput = document.getElementById("intentTasksInput");
    const intentTasksRaw = intentTasksInput ? intentTasksInput.value.trim() : "";
    const intentTasks = intentTasksRaw
      .split("\n")
      .map(t => t.trim().replace(/^[-*•]\s*/, "").trim())
      .filter(t => t.length > 0)
      .map(t => ({ text: t, completed: false }));

    if (intentTasks.length > 0) {
      payload.intent_tasks = intentTasks;
    }

    if (currentType === "standard") {
      const activeDur = Array.from(els.durChips).find((c) =>
        c.classList.contains("active"),
      );
      const custom = parseInt(els.customMin.value, 10);
      payload.duration =
        custom || (activeDur ? parseInt(activeDur.dataset.min, 10) : 60);
    } else {
      payload.focus_minutes = parseInt(els.pomoFocus.value, 10) || 25;
      payload.break_minutes = parseInt(els.pomoBreak.value, 10) || 5;
      payload.cycles = parseInt(els.pomoCycles.value, 10) || 4;
      payload.duration =
        (payload.focus_minutes + payload.break_minutes) * payload.cycles;
    }

    try {
      const res = await api("POST", "/api/start", payload);
      if (res.status === "ok") {
        refresh();
      } else {
        alert(res.message || "Failed to start");
      }
    } catch (e) {
      console.error("Start failed:", e);
      alert("Communication failed.");
    } finally {
      els.btnIntentConfirm.innerHTML = originalIntentHTML;
      els.btnIntentConfirm.disabled = false;
      els.btnIntentConfirm.removeAttribute("aria-busy");
      isStarting = false;
    }
  });

  els.mbBtnRescue.addEventListener("click", async () => {
    const originalRescueHTML = els.mbBtnRescue.innerHTML;
    els.mbBtnRescue.innerHTML = '<span class="btn-spinner"></span> Activating...';
    els.mbBtnRescue.disabled = true;
    els.mbBtnRescue.setAttribute("aria-busy", "true");
    
    try {
      const dur = parseInt(els.rescueDur.value, 10) || 10;
      const res = await api("POST", "/api/start", {
        duration: dur,
        mode: "whitelist",
        session_type: "rescue",
      });
      if (res.status === "ok") {
        refresh();
      }
    } finally {
      els.mbBtnRescue.innerHTML = originalRescueHTML;
      els.mbBtnRescue.disabled = false;
      els.mbBtnRescue.removeAttribute("aria-busy");
    }
  });

  els.btnStop.addEventListener("click", async () => {
    AudioManager.play("unlock");
    // S3: Show inline passphrase dialog instead of opening browser
    const dialog = document.getElementById("unlockDialog");
    if (dialog) {
      dialog.classList.remove("hidden");
      const input = document.getElementById("unlockPassphrase");
      if (input) {
        input.value = "";
        input.focus();
      }
      const errEl = document.getElementById("unlockError");
      if (errEl) errEl.classList.add("hidden");
    }
  });

  // S3: Inline unlock dialog handlers
  const btnUnlockConfirm = document.getElementById("btnUnlockConfirm");
  const btnUnlockCancel = document.getElementById("btnUnlockCancel");
  const unlockPassphrase = document.getElementById("unlockPassphrase");

  if (btnUnlockConfirm) {
    btnUnlockConfirm.addEventListener("click", async () => {
      const key = unlockPassphrase.value;
      const errEl = document.getElementById("unlockError");
      if (!key) {
        errEl.textContent = "Enter passphrase.";
        errEl.classList.remove("hidden");
        return;
      }

      btnUnlockConfirm.disabled = true;
      const originalUnlockHTML = btnUnlockConfirm.innerHTML;
      btnUnlockConfirm.innerHTML = '<span class="btn-spinner"></span> Unlocking...';
      btnUnlockConfirm.setAttribute("aria-busy", "true");

      try {
        const res = await api("POST", "/api/stop", { key });
        if (res.status === "pending" || res.status === "ok") {
          document.getElementById("unlockDialog").classList.add("hidden");
          refresh();
        } else {
          errEl.textContent = res.message || "Invalid passphrase.";
          errEl.classList.remove("hidden");
        }
      } finally {
        btnUnlockConfirm.disabled = false;
        btnUnlockConfirm.innerHTML = originalUnlockHTML;
        btnUnlockConfirm.removeAttribute("aria-busy");
      }
    });
  }

  if (btnUnlockCancel) {
    btnUnlockCancel.addEventListener("click", () => {
      document.getElementById("unlockDialog").classList.add("hidden");
    });
  }

  if (unlockPassphrase) {
    unlockPassphrase.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && btnUnlockConfirm) btnUnlockConfirm.click();
    });
  }
}

let globalPollInterval = null;

window.onPopoverShow = () => {
  loadSettings();
  fetchGroups();
  refresh();
  connectSSE();
  if (!globalPollInterval) globalPollInterval = setInterval(refresh, 1000);
};

async function loadSettings() {
  try {
    const res = await api("GET", "/api/settings");
    if (res.settings) {
      AudioManager.settings = res.settings;
    }
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

window.onPopoverHide = () => {
  // Keep SSE active to drive the native menubar countdown via nativeCallback
  if (countdownInterval) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
  if (globalPollInterval) {
    clearInterval(globalPollInterval);
    globalPollInterval = null;
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  initEvents();
  await loadApiToken();
  // S8: Load settings and refresh status immediately, don't wait for onPopoverShow
  loadSettings();
  fetchGroups();
  refresh();
  connectSSE();
  if (!globalPollInterval) globalPollInterval = setInterval(refresh, 1000);
});

let eventSource = null;
function connectSSE() {
  if (eventSource && (eventSource.readyState === 0 || eventSource.readyState === 1)) return;
  if (eventSource) eventSource.close();
  eventSource = new EventSource(API + "/api/stream");
  
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      renderStatus(data);
      if (window.webkit && window.webkit.messageHandlers.nativeCallback) {
        window.webkit.messageHandlers.nativeCallback.postMessage({ action: "syncState", data: data });
      }
    } catch (err) {
      console.error("SSE parse error:", err);
    }
  };
  
  eventSource.onerror = () => {
    console.warn("SSE connection lost. Reconnecting in 3s...");
    eventSource.close();
    setTimeout(connectSSE, 3000);
  };
}
