/**
 * ForcedFocus — Web UI Client
 * Handles countdown timer, API calls, domain management, and UI state.
 */

const API = "";
let currentMode = "blacklist";
let selectedDuration = 120;
let countdownInterval = null;
let pollInterval = null;
let totalSessionSeconds = 0;
let currentRemaining = 0;

let sessionType = "standard";
let pomoFocusMin = 25;
let pomoBreakMin = 5;
let pomoCycles = 4;

let scheduleType = "now"; // 'now', 'in', 'at'
let availableGroups = {};
let selectedGroups = new Set();
let apiToken = ""; // Per-launch API token for mutation auth
let lastActiveState = false;
let sessionSnapshot = { intent: "", tasks: [] };

// ── HTML Sanitization ────────────────────────────────────────────────────────

// P6: Static character map instead of throwaway DOM elements
function escapeHtml(str) {
  return String(str).replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      })[c],
  );
}

// Audio Manager
const AudioManager = {
  settings: {},
  availableSounds: [],
  _current: null,
  play: function (type) {
    // 'type' is start, rescue, unlock, etc.
    const file = this.settings[`sound_${type}`];
    if (!file) return;
    // R3: Stop previous audio before playing new one
    if (this._current) {
      this._current.pause();
      this._current = null;
    }
    this._current = new Audio("/sounds/" + encodeURIComponent(file));
    this._current.play().catch((e) => console.log("Audio error:", e));
  },
};

// ── DOM Elements ─────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
  statusBadge: $("#statusBadge"),
  timerSection: $("#timerSection"),
  timerRing: $("#timerRing"),
  timerProgress: $("#timerProgress"),
  timerValue: $("#timerValue"),
  timerLabel: $("#timerLabel"),
  pomoStatus: $("#pomoStatus"),
  pomoPhase: $("#pomoPhase"),
  pomoCycleDisplay: $("#pomoCycleDisplay"),
  pomoNextTimeDisplay: $("#pomoNextTimeDisplay"),
  modeDisplay: $("#modeDisplay"),
  expiresDisplay: $("#expiresDisplay"),
  modeCard: $("#modeCard"),
  sessionSettingsCard: $("#sessionSettingsCard"),
  sessionSettingsTitle: $("#sessionSettingsTitle"),
  standardSettingsArea: $("#standardSettingsArea"),
  pomodoroSettingsArea: $("#pomodoroSettingsArea"),
  btnStart: $("#btnStart"),
  btnStop: $("#btnStop"),
  unlockInfo: $("#unlockInfo"),
  blacklistInput: $("#blacklistInput"),
  whitelistInput: $("#whitelistInput"),
  blacklistDomains: $("#blacklistDomains"),
  whitelistDomains: $("#whitelistDomains"),
  blacklistCount: $("#blacklistCount"),
  whitelistCount: $("#whitelistCount"),
  stopModal: $("#stopModal"),
  passphraseInput: $("#passphraseInput"),
  modalError: $("#modalError"),
  toast: $("#toast"),
  customMinutes: $("#customMinutes"),
  pomoFocus: $("#pomoFocus"),
  pomoBreak: $("#pomoBreak"),
  pomoCycles: $("#pomoCycles"),
  pomoSummary: $("#pomoSummary"),
  scheduleCard: $("#scheduleCard"),
  scheduleInWrapper: $("#scheduleInWrapper"),
  scheduleAtWrapper: $("#scheduleAtWrapper"),
  scheduleIn: $("#scheduleIn"),
  scheduleAt: $("#scheduleAt"),
  upcomingSchedulesCard: $("#upcomingSchedulesCard"),
  upcomingSchedulesList: $("#upcomingSchedulesList"),
  upcomingSchedulesCount: $("#upcomingSchedulesCount"),
  rescueCard: $("#rescueCard"),
  rescueDuration: $("#rescueDuration"),
  btnRescue: $("#btnRescue"),
  sessionGroups: $("#sessionGroups"),
};

// ── API Helpers ──────────────────────────────────────────────────────────────

const activeRequests = new Map();

async function api(method, path, body = null) {
  const headers = { "Content-Type": "application/json" };
  // Include API token for mutation requests (POST, DELETE)
  if (method !== "GET" && apiToken) {
    headers["X-API-Token"] = apiToken;
  }
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
    if (err.name === "AbortError") return new Promise(() => {}); // Never resolves if aborted
    console.error("API Error:", err);
    return { status: "error", message: "Communication failed." };
  }
}

// ── Toast ────────────────────────────────────────────────────────────────────

let _toastTimeout = null; // R2: Track timeout to prevent stacking

function showToast(msg, duration = 3000) {
  if (_toastTimeout) clearTimeout(_toastTimeout);
  els.toast.textContent = msg;
  els.toast.classList.remove("hidden");
  els.toast.classList.add("show");
  _toastTimeout = setTimeout(() => {
    els.toast.classList.remove("show");
    _toastTimeout = setTimeout(() => {
      els.toast.classList.add("hidden");
      _toastTimeout = null;
    }, 300);
  }, duration);
}

// ── Timer ────────────────────────────────────────────────────────────────────

function formatTime(totalSeconds) {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function updateTimerDisplay(remMs, isInitial = false) {
  const remSecs = Math.max(0, Math.ceil(remMs / 1000));
  els.timerValue.textContent = formatTime(remSecs);

  // Update progress ring (Clockwise fill)
  const circ = 565.48; // 2 * Math.PI * 90
  const totalMs = totalSessionSeconds * 1000;
  const prog = totalMs > 0 ? 1 - remMs / totalMs : 0;

  if (isInitial) els.timerProgress.style.transition = "none";
  els.timerProgress.style.strokeDasharray = `${Math.max(0, Math.min(1, prog)) * circ} ${circ}`;
  els.timerProgress.style.strokeDashoffset = 0;
  if (isInitial) {
    els.timerProgress.offsetHeight; // force reflow
    els.timerProgress.style.transition = "";
  }
}

function startCountdown(remainingSeconds) {
  if (countdownInterval && Math.abs(currentRemaining - remainingSeconds) <= 2)
    return;
  if (countdownInterval) clearInterval(countdownInterval);

  const startTime = Date.now();
  const durationMs = remainingSeconds * 1000;
  const endTime = startTime + durationMs;
  currentRemaining = remainingSeconds;

  let isFirst = true;
  const tick = () => {
    const now = Date.now();
    const remMs = endTime - now;

    if (remMs <= 0) {
      clearInterval(countdownInterval);
      countdownInterval = null;
      updateTimerDisplay(0);
      refreshStatus();
      return;
    }

    currentRemaining = Math.ceil(remMs / 1000);
    updateTimerDisplay(remMs, isFirst);
    isFirst = false;
  };

  tick();
  countdownInterval = setInterval(tick, 100); // 10fps for buttery smooth movement
}

function stopCountdown() {
  if (countdownInterval) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
  updateTimerDisplay(0);
  els.timerProgress.style.strokeDashoffset = 565.48;
}

let isStarting = false;

// ── UI State ─────────────────────────────────────────────────────────────────

function setActiveUI(status) {
  if (isStarting) return;

  const active = status.active;
  const schedules = status.schedules || [];
  const hasSchedules = schedules.length > 0;

  // Determine the effective primary state for the UI
  const isPrimaryScheduled = !active && hasSchedules;
  const isFullyActive = active;

  // Recap detection: Active -> Idle
  if (lastActiveState === true && isFullyActive === false) {
    // Session just ended
    showRecap(sessionSnapshot);
  }
  
  if (isFullyActive) {
    // Capture snapshot while active
    sessionSnapshot.intent = status.intent || "";
    sessionSnapshot.tasks = status.intent_tasks || [];
  }

  lastActiveState = isFullyActive;

  // ── Centralized Reset ──
  // Clear all potential state classes before applying current state
  els.statusBadge.classList.remove("active", "break", "pulse");
  els.timerRing.classList.remove("active", "break");
  const logoIcon = $(".logo-icon");
  if (logoIcon) logoIcon.classList.remove("pulse");

  // Status badge
  els.statusBadge.classList.toggle(
    "active",
    isFullyActive || isPrimaryScheduled,
  );

  // Logo pulse & Status glow
  if (logoIcon) {
    logoIcon.classList.toggle("pulse", isFullyActive);
  }

  if (isPrimaryScheduled) {
    els.statusBadge.querySelector(".status-text").textContent = "SCHEDULED";
  } else {
    els.statusBadge.querySelector(".status-text").textContent = isFullyActive
      ? status.mode.toUpperCase()
      : "Idle";
  }

  // Timer ring
  els.timerRing.classList.toggle("active", isFullyActive || isPrimaryScheduled);

  // Mode & duration cards
  els.modeCard.classList.toggle("disabled", isFullyActive);
  els.sessionSettingsCard.classList.toggle("disabled", isFullyActive);
  els.scheduleCard.classList.toggle("disabled", isFullyActive);
  els.rescueCard.classList.toggle("disabled", isFullyActive);

  // Start/stop buttons
  els.btnStart.classList.toggle("hidden", isFullyActive);
  els.btnStop.classList.toggle("hidden", !isFullyActive);

  // Update Upcoming Schedules List (P2: skip if data unchanged)
  if (hasSchedules) {
    const scheduleJSON = JSON.stringify(schedules);
    if (scheduleJSON !== _lastScheduleJSON) {
      _lastScheduleJSON = scheduleJSON;
      els.upcomingSchedulesCard.classList.remove("hidden");
      els.upcomingSchedulesCount.textContent = schedules.length;
      els.upcomingSchedulesList.innerHTML = "";
      schedules.forEach((sch) => {
        const li = document.createElement("li");
        li.className = "calendar-item";

        let monthStr = "---";
        let dayStr = "--";
        let timeStr = String(sch.starts_at || "");

        try {
          const parts = String(sch.starts_at || "").split(" ");
          if (parts.length >= 3) {
            const dateParts = parts[0].split("-");
            if (dateParts.length === 3) {
              const m = parseInt(dateParts[1], 10);
              const d = parseInt(dateParts[2], 10);
              const monthNames = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
              ];
              monthStr = monthNames[m - 1] || "---";
              dayStr = d.toString();
              timeStr = `${parts[1]} ${parts[2]}`;
            }
          }
        } catch (e) {}

        // Build DOM safely to prevent XSS (no innerHTML with server data)
        const calDate = document.createElement("div");
        calDate.className = "cal-date";
        const calMonth = document.createElement("span");
        calMonth.className = "cal-month";
        calMonth.textContent = monthStr;
        const calDay = document.createElement("span");
        calDay.className = "cal-day";
        calDay.textContent = dayStr;
        calDate.appendChild(calMonth);
        calDate.appendChild(calDay);

        const calDetails = document.createElement("div");
        calDetails.className = "cal-details";
        const calTime = document.createElement("div");
        calTime.className = "cal-time";
        calTime.textContent = timeStr;
        const calTitle = document.createElement("div");
        calTitle.className = "cal-title";
        calTitle.textContent = String(sch.mode || "").toUpperCase() + " ";
        const calType = document.createElement("span");
        calType.className = "cal-type";
        calType.textContent = "• " + String(sch.session_type || "");
        calTitle.appendChild(calType);
        const calDuration = document.createElement("div");
        calDuration.className = "cal-duration";
        calDuration.textContent =
          "⏳ " + String(sch.duration_minutes || 0) + " mins";
        calDetails.appendChild(calTime);
        calDetails.appendChild(calTitle);
        calDetails.appendChild(calDuration);

        li.appendChild(calDate);
        li.appendChild(calDetails);
        els.upcomingSchedulesList.appendChild(li);
      });
    } // P2: end scheduleJSON changed block
  } else {
    els.upcomingSchedulesCard.classList.add("hidden");
    if (_lastScheduleJSON !== "") {
      els.upcomingSchedulesList.innerHTML = "";
      _lastScheduleJSON = "";
    }
  }

  // ── 4. Main Timer Logic ──
  if (isFullyActive) {
    const intentContainer = document.getElementById("activeIntentContainer");
    const intentDisplay = document.getElementById("activeIntentDisplay");
    const intentTasksContainer = document.getElementById("activeIntentTasks");

    if (intentContainer) {
      if (status.intent) {
        intentContainer.style.display = "block";
        if (intentDisplay) {
          intentDisplay.textContent = status.intent;
        }
        if (intentTasksContainer) {
          renderIntentTasks(intentTasksContainer, status.intent_tasks || []);
        }
      } else {
        intentContainer.style.display = "none";
      }
    }
    // Mode & expires info
    if (status.session_type === "rescue") {
      els.modeDisplay.textContent = `Mode: Rescue Throne 🛡️`;
    } else {
      els.modeDisplay.textContent = `Mode: ${status.mode}`;
    }
    els.expiresDisplay.textContent = `Expires: ${status.expires_at}`;

    if (status.session_type === "pomodoro") {
      els.pomoStatus.classList.remove("hidden");
      els.pomoPhase.textContent = status.pomo_phase.toUpperCase();
      els.pomoPhase.className = `pomo-phase-badge ${status.pomo_phase}`;
      els.pomoCycleDisplay.textContent = `Cycle ${status.pomo_current_cycle}/${status.pomo_total_cycles}`;

      if (status.pomo_phase_expiry_time) {
        const nextType = status.pomo_phase === "focus" ? "break" : "focus";
        els.pomoNextTimeDisplay.textContent = `Next ${nextType} at ${status.pomo_phase_expiry_time}`;
        els.pomoNextTimeDisplay.style.display = "block";
      } else {
        els.pomoNextTimeDisplay.style.display = "none";
      }

      // Timer ring color
      els.timerRing.classList.toggle("break", status.pomo_phase === "break");
      els.timerLabel.textContent = status.pomo_phase.toUpperCase();

      totalSessionSeconds = status.pomo_phase_total || 1;
      startCountdown(status.pomo_phase_remaining || 0);
    } else {
      els.pomoStatus.classList.add("hidden");
      els.timerRing.classList.remove("break");
      els.timerLabel.textContent = "REMAINING";

      totalSessionSeconds =
        status.total_duration_seconds || status.remaining_seconds;
      startCountdown(status.remaining_seconds);
    }

    // Handle pending unlock box
    if (status.pending_unlock) {
      els.unlockInfo.classList.remove("hidden");
      const unlockSecs = status.pending_unlock_seconds || 0;
      els.unlockInfo.querySelector("p").textContent =
        `⏱ Unlock pending — releases at ${status.pending_unlock} (${formatTime(unlockSecs)} left)`;
    } else {
      els.unlockInfo.classList.add("hidden");
    }
  } else if (isPrimaryScheduled) {
    // Scheduled state (not yet active)
    const nextSch = schedules[0];
    const secs = nextSch.starting_in_seconds || 0;

    els.timerRing.classList.remove("break");
    els.modeDisplay.textContent = `Mode: ${nextSch.mode}`;
    els.expiresDisplay.textContent = `Starts at: ${nextSch.starts_at}`;
    els.pomoStatus.classList.add("hidden");
    els.unlockInfo.classList.add("hidden");
    
    const intentContainer = document.getElementById("activeIntentContainer");
    if (intentContainer) intentContainer.style.display = "none";

    if (secs <= 0) {
      els.timerLabel.textContent = "STARTING...";
      els.statusBadge.classList.add("pulse"); // Visual cue for transition
      els.timerValue.textContent = "00:00:00";
      stopCountdown();
    } else {
      els.timerLabel.textContent = "STARTING IN";
      els.statusBadge.classList.remove("pulse");
      totalSessionSeconds = 0; // disables progress ring animation
      startCountdown(secs);
    }
  } else {
    // Idle state
    els.modeDisplay.textContent = "—";
    els.expiresDisplay.textContent = "—";
    els.pomoStatus.classList.add("hidden");
    els.timerRing.classList.remove("break");
    els.timerLabel.textContent = "READY";
    els.unlockInfo.classList.add("hidden");

    const intentContainer = document.getElementById("activeIntentContainer");
    if (intentContainer) intentContainer.style.display = "none";

    totalSessionSeconds = 0;
    stopCountdown();
    els.timerValue.textContent = "00:00:00";
  }
}

// ── Refresh Status ───────────────────────────────────────────────────────────

// S1: Track state for detecting phase transitions
let _lastPomoPhase = null;
let _lastActiveState = null;
let _lastScheduleJSON = ""; // P2: Track schedule data to avoid DOM thrash

async function refreshStatus() {
  const data = await api("GET", "/api/status");
  if (data.status === "ok") {
    // S1: Detect phase transitions that require timer reset
    const phaseChanged = data.pomo_phase !== _lastPomoPhase;
    const activeChanged = data.active !== _lastActiveState;
    if (phaseChanged || activeChanged) {
      if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
      }
    }
    _lastPomoPhase = data.pomo_phase || null;
    _lastActiveState = data.active;
    setActiveUI(data);
  }
}

// ── Refresh Lists ────────────────────────────────────────────────────────────

async function refreshLists() {
  const data = await api("GET", "/api/lists");
  if (data.status !== "ok") return;

  const lists = data.lists;
  renderDomainList(els.blacklistDomains, lists.blacklist || [], "blacklist");
  renderDomainList(els.whitelistDomains, lists.whitelist || [], "whitelist");
  els.blacklistCount.textContent = (lists.blacklist || []).length;
  els.whitelistCount.textContent = (lists.whitelist || []).length;
}

function renderDomainList(container, domains, listName) {
  container.innerHTML = "";
  domains.forEach((domain) => {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = domain;
    const removeBtn = document.createElement("button");
    removeBtn.className = "remove-btn";
    removeBtn.dataset.list = listName;
    removeBtn.dataset.domain = domain;
    removeBtn.textContent = "✕";
    removeBtn.setAttribute("aria-label", `Remove ${domain}`);
    removeBtn.addEventListener("click", async () => {
      removeBtn.disabled = true;
      try {
        const res = await api("DELETE", `/api/lists/${listName}/${domain}`);
        if (res.status === "ok") {
          showToast(`Removed ${domain}`);
          refreshLists();
        } else {
          showToast("Error: " + res.message);
        }
      } finally {
        removeBtn.disabled = false;
      }
    });
    li.appendChild(span);
    li.appendChild(removeBtn);
    container.appendChild(li);
  });
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
    li.style.gap = "10px";
    li.style.margin = "2px 0";
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

function showRecap(data) {
  const modal = document.getElementById("recapModal");
  const intentDisplay = document.getElementById("recapIntentDisplay");
  const tasksList = document.getElementById("recapTasksList");
  const tasksSection = document.getElementById("recapTasksSection");
  const title = document.getElementById("recapTitle");
  
  if (!modal || !intentDisplay || !tasksList) return;
  
  intentDisplay.textContent = data.intent || "No goal specified";
  tasksList.innerHTML = "";
  
  const tasks = data.tasks || [];
  if (tasks.length === 0) {
    tasksSection.style.display = "none";
    title.textContent = "Session Complete!";
  } else {
    tasksSection.style.display = "block";
    const completedCount = tasks.filter(t => t.completed).length;
    const totalCount = tasks.length;
    
    if (completedCount === totalCount) {
      title.textContent = "Perfect Session! 🏆";
    } else if (completedCount > 0) {
      title.textContent = "Great Progress! 👏";
    } else {
      title.textContent = "Session Finished";
    }
    
    tasks.forEach(task => {
      const item = document.createElement("div");
      item.className = `recap-task-item ${task.completed ? "completed" : ""}`;
      item.dir = "auto";
      
      const check = document.createElement("div");
      check.className = `recap-check ${task.completed ? "done" : "todo"}`;
      check.textContent = task.completed ? "✓" : "";
      
      const text = document.createElement("div");
      text.className = "recap-task-text";
      text.textContent = task.text;
      
      item.appendChild(check);
      item.appendChild(text);
      tasksList.appendChild(item);
    });
  }
  
  modal.classList.remove("hidden");
}

document.getElementById("btnContinueRecap")?.addEventListener("click", () => {
  document.getElementById("recapModal").classList.add("hidden");
});

// ── Event Handlers ───────────────────────────────────────────────────────────

function initEvents() {
  // Tab Navigation
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      // Remove active from all tabs and panes
      $$(".nav-btn").forEach((b) => b.classList.remove("active"));
      $$(".tab-pane").forEach((p) => p.classList.remove("active"));

      // Add active to clicked tab and corresponding pane
      btn.classList.add("active");
      const targetId = btn.dataset.tab;
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // Mode toggle (excluding nav tabs)
  $$(".mode-btn:not(.session-type-btn):not(.schedule-type-btn)").forEach(
    (btn) => {
      btn.addEventListener("click", () => {
        $$(".mode-btn:not(.session-type-btn):not(.schedule-type-btn)").forEach(
          (b) => b.classList.remove("active"),
        );
        btn.classList.add("active");
        currentMode = btn.dataset.mode;
      });
    },
  );

  // Schedule type toggle
  $$(".schedule-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".schedule-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      scheduleType = btn.dataset.type;

      if (scheduleType === "in") {
        els.scheduleInWrapper.classList.remove("hidden");
        els.scheduleAtWrapper.classList.add("hidden");
      } else if (scheduleType === "at") {
        els.scheduleInWrapper.classList.add("hidden");
        els.scheduleAtWrapper.classList.remove("hidden");
      } else {
        els.scheduleInWrapper.classList.add("hidden");
        els.scheduleAtWrapper.classList.add("hidden");
      }
    });
  });

  function updatePomoSummary() {
    pomoFocusMin = parseInt(els.pomoFocus.value) || 25;
    pomoBreakMin = parseInt(els.pomoBreak.value) || 5;
    pomoCycles = parseInt(els.pomoCycles.value) || 4;
    const total = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    const h = Math.floor(total / 60);
    const m = total % 60;
    els.pomoSummary.textContent = `Total: ${h}h ${String(m).padStart(2, "0")}m (${pomoCycles} × ${pomoFocusMin}m focus + ${pomoBreakMin}m break)`;
  }

  $$(".session-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".session-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      sessionType = btn.dataset.type;
      if (sessionType === "pomodoro") {
        els.standardSettingsArea.classList.add("hidden");
        els.pomodoroSettingsArea.classList.remove("hidden");
        els.sessionSettingsTitle.textContent = "🍅 Pomodoro Settings";
        updatePomoSummary();
      } else {
        els.standardSettingsArea.classList.remove("hidden");
        els.pomodoroSettingsArea.classList.add("hidden");
        els.sessionSettingsTitle.textContent = "Session Duration";
      }
    });
  });

  $$(".pomo-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".pomo-preset").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      els.pomoFocus.value = btn.dataset.focus;
      els.pomoBreak.value = btn.dataset.break;
      updatePomoSummary();
    });
  });

  [els.pomoFocus, els.pomoBreak, els.pomoCycles].forEach((el) => {
    el.addEventListener("input", () => {
      $$(".pomo-preset").forEach((b) => b.classList.remove("active"));
      updatePomoSummary();
    });
  });

  // Duration buttons (exclude pomo-preset buttons which share .dur-btn class)
  $$(".dur-btn:not(.pomo-preset)").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".dur-btn:not(.pomo-preset)").forEach((b) =>
        b.classList.remove("active"),
      );
      btn.classList.add("active");
      selectedDuration = parseInt(btn.dataset.minutes);
      els.customMinutes.value = "";
    });
  });

  // Custom duration
  els.customMinutes.addEventListener("input", () => {
    const val = parseInt(els.customMinutes.value);
    if (val > 0) {
      $$(".dur-btn").forEach((b) => b.classList.remove("active"));
      selectedDuration = val;
    }
  });

  // Start button -> Shows Intent Modal
  els.btnStart.addEventListener("click", () => {
    // Basic validation before showing modal
    if (scheduleType === "in") {
      const min = parseInt(els.scheduleIn.value);
      if (!min || min < 1) {
        showToast("Please enter a valid number of minutes.");
        return;
      }
    } else if (scheduleType === "at") {
      const time = els.scheduleAt.value;
      if (!time) {
        showToast("Please select a valid date and time.");
        return;
      }
    }

    const intentModal = $("#intentModal");
    const intentInput = $("#intentModalInput");
    const intentTasksInput = $("#intentTasksInput");
    if (intentModal && intentInput) {
      intentModal.classList.remove("hidden");
      intentInput.value = "";
      if (intentTasksInput) intentTasksInput.value = "";
      intentInput.focus();
    }
  });

  const intentInput = $("#intentModalInput");
  if (intentInput) {
    intentInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const btnConfirmIntent = $("#btnConfirmIntent");
        if (btnConfirmIntent) btnConfirmIntent.click();
      }
    });
  }

  // Cancel Intent
  const btnCancelIntent = $("#btnCancelIntent");
  if (btnCancelIntent) {
    btnCancelIntent.addEventListener("click", () => {
      $("#intentModal").classList.add("hidden");
    });
  }

  // Confirm Intent & Start Session
  const btnConfirmIntent = $("#btnConfirmIntent");
  if (btnConfirmIntent) {
    btnConfirmIntent.addEventListener("click", async () => {
      $("#intentModal").classList.add("hidden");
      let payload = {};
      const intentVal = $("#intentModalInput").value.trim();
      const intentTasksRaw = $("#intentTasksInput") ? $("#intentTasksInput").value.trim() : "";
      const intentTasks = intentTasksRaw
        .split("\n")
        .map(t => t.trim().replace(/^[-*•]\s*/, "").trim())
        .filter(t => t.length > 0)
        .map(t => ({ text: t, completed: false }));

      if (sessionType === "pomodoro") {
        const totalMin = (pomoFocusMin + pomoBreakMin) * pomoCycles;
        totalSessionSeconds = totalMin * 60;
        payload = {
          duration: totalMin,
          mode: currentMode,
          session_type: "pomodoro",
          focus_minutes: pomoFocusMin,
          break_minutes: pomoBreakMin,
          cycles: pomoCycles,
        };
      } else {
        const duration = selectedDuration;
        totalSessionSeconds = duration * 60;
        payload = { duration, mode: currentMode, session_type: "standard" };
      }

      payload.groups = Array.from(selectedGroups);
      if (intentVal) {
        payload.intent = intentVal;
      }
      if (intentTasks.length > 0) {
        payload.intent_tasks = intentTasks;
      }

      if (scheduleType === "in") {
        payload.schedule_in = parseInt(els.scheduleIn.value);
      } else if (scheduleType === "at") {
        payload.schedule_at = els.scheduleAt.value;
      }

      const originalBtnHTML = els.btnStart.innerHTML;
      els.btnStart.textContent = "⏳ Starting...";
      els.btnStart.disabled = true;
      isStarting = true;

      try {
        const res = await api("POST", "/api/start", payload);
        if (res.status === "ok") {
          if (payload.schedule_in || payload.schedule_at) {
            showToast("Session scheduled successfully! 🗓️");
          } else {
            showToast("Session started! 🚀");
          }
        } else {
          showToast(`Error: ${res.message || "Failed to start"}`);
        }
      } catch (err) {
        showToast("Connection failed. Is the daemon running?");
      } finally {
        els.btnStart.innerHTML = originalBtnHTML;
        els.btnStart.disabled = false;
        isStarting = false;
      }
      refreshStatus();
    });
  }

  // Rescue button
  els.btnRescue.addEventListener("click", async () => {
    const duration = parseInt(els.rescueDuration.value, 10) || 10;
    const payload = {
      duration: duration,
      mode: "whitelist",
      session_type: "rescue",
    };
    els.btnRescue.textContent = "⏳ Activating...";
    els.btnRescue.disabled = true;
    try {
      const res = await api("POST", "/api/start", payload);
      if (res.status === "ok") {
        AudioManager.play("rescue");
        showToast(res.message);
        refreshStatus();
      } else {
        showToast(res.message || "Failed to activate Rescue Throne.");
      }
    } finally {
      els.btnRescue.innerHTML =
        '<span class="btn-icon">⚡</span> Activate Rescue';
      els.btnRescue.disabled = false;
    }
  });

  // Stop button → open modal
  els.btnStop.addEventListener("click", () => {
    AudioManager.play("unlock");
    els.stopModal.classList.remove("hidden");
    els.passphraseInput.value = "";
    els.modalError.classList.add("hidden");
    els.passphraseInput.focus();
  });

  // Cancel stop
  $("#btnCancelStop").addEventListener("click", () => {
    els.stopModal.classList.add("hidden");
  });

  // Confirm stop
  $("#btnConfirmStop").addEventListener("click", async () => {
    const key = els.passphraseInput.value;
    if (!key) {
      els.modalError.textContent = "Please enter your passphrase.";
      els.modalError.classList.remove("hidden");
      return;
    }

    const btn = $("#btnConfirmStop");
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Stopping...";

    try {
      const res = await api("POST", "/api/stop", { key });
      if (res.status === "pending" || res.status === "ok") {
        els.stopModal.classList.add("hidden");
        showToast(res.message);
        refreshStatus();
      } else {
        els.modalError.textContent = res.message || "Invalid passphrase.";
        els.modalError.classList.remove("hidden");
      }
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });

  // Modal passphrase enter key
  els.passphraseInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("#btnConfirmStop").click();
  });

  // Close modal on overlay click
  els.stopModal.addEventListener("click", (e) => {
    if (e.target === els.stopModal) els.stopModal.classList.add("hidden");
  });

  // Add domain: blacklist
  $("#btnAddBlacklist").addEventListener("click", () => addDomain("blacklist"));
  els.blacklistInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      addDomain("blacklist");
    }
  });

  // Add domain: whitelist
  $("#btnAddWhitelist").addEventListener("click", () => addDomain("whitelist"));
  els.whitelistInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      addDomain("whitelist");
    }
  });

  // R5: Close modal on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.stopModal.classList.contains("hidden")) {
      els.stopModal.classList.add("hidden");
    }
  });
}

function extractDomain(input) {
  let d = input.trim().toLowerCase();
  // Strip protocol
  d = d.replace(/^https?:\/\//, "");
  // Strip path, query, hash
  d = d.split("/")[0].split("?")[0].split("#")[0];
  // Strip port
  d = d.split(":")[0];
  // Strip wildcard characters (e.g., *.example.com → example.com, example.com* → example.com)
  d = d.replace(/^\*\.?/, "").replace(/\*$/, "");
  return d;
}

async function addDomain(listName) {
  const input =
    listName === "blacklist" ? els.blacklistInput : els.whitelistInput;
  const btnId =
    listName === "blacklist" ? "#btnAddBlacklist" : "#btnAddWhitelist";
  const btn = $(btnId);

  const raw = input.value.trim();
  if (!raw) return;

  if (btn) btn.disabled = true;
  const originalText = btn ? btn.textContent : "";
  if (btn) btn.textContent = "Adding...";

  try {
    // Split by newlines to support bulk paste
    const lines = raw
      .split(/[\n\r]+/)
      .map((l) => l.trim())
      .filter(Boolean);
    const domains = [];
    const invalid = [];

    for (const line of lines) {
      const domain = extractDomain(line);
      // Basic validation
      if (/^[a-z0-9]([a-z0-9\-]*\.)+[a-z]{2,}$/.test(domain)) {
        domains.push(domain);
      } else {
        invalid.push(line);
      }
    }

    if (domains.length === 0) {
      showToast(
        "Invalid domain. Example: reddit.com or https://reddit.com/r/test",
      );
      return;
    }

    if (invalid.length > 0) {
      showToast(
        `Skipped ${invalid.length} invalid: ${invalid.slice(0, 3).join(", ")}`,
      );
    }

    // Use bulk endpoint for multiple domains, single endpoint for one
    if (domains.length === 1) {
      const res = await api("POST", `/api/lists/${listName}`, {
        domain: domains[0],
      });
      if (res.status === "ok") {
        input.value = "";
        showToast(`Added ${domains[0]} to ${listName}`);
        refreshLists();
      } else {
        showToast("Error: " + res.message);
      }
    } else {
      const res = await api("POST", `/api/lists/${listName}/bulk`, { domains });
      if (res.status === "ok") {
        input.value = "";
        showToast(`Added ${domains.length} domains to ${listName}`);
        refreshLists();
      } else {
        showToast("Error: " + res.message);
      }
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function loadApiToken() {
  try {
    const res = await fetch("/api/token");
    const data = await res.json();
    if (data.token) {
      apiToken = data.token;
    }
  } catch (e) {
    console.error("Failed to load API token:", e);
  }
}

async function init() {
  initEvents();
  await loadApiToken();
  await refreshStatus();
  await refreshLists();
  await refreshGroups();
  await loadSettings();

  // S10: Set min datetime to now, preventing past date selection
  if (els.scheduleAt) {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const minVal = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    els.scheduleAt.min = minVal;
  }

  // Poll status every 2 seconds
  pollInterval = setInterval(refreshStatus, 2000);

  // P4: Pause polling when tab is hidden to save resources
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    } else {
      refreshStatus(); // Immediate sync on return
      pollInterval = setInterval(refreshStatus, 2000);
    }
  });
}

async function loadSettings() {
  try {
    const [settingsRes, soundsRes] = await Promise.all([
      api("GET", "/api/settings"),
      api("GET", "/api/sounds"),
    ]);
    if (settingsRes.settings) {
      AudioManager.settings = settingsRes.settings;
    }
    if (soundsRes.sounds) {
      AudioManager.availableSounds = soundsRes.sounds;
    }
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

async function refreshGroups() {
  const data = await api("GET", "/api/groups");
  if (data.status === "ok") {
    availableGroups = data.groups || {};
    renderSessionGroups();
  }
}

function renderSessionGroups() {
  if (Object.keys(availableGroups).length === 0) {
    els.sessionGroups.innerHTML =
      '<div style="color: var(--text-muted); font-size: 13px;">No groups configured in Settings.</div>';
    return;
  }

  els.sessionGroups.innerHTML = "";
  for (const name of Object.keys(availableGroups)) {
    const btn = document.createElement("button");
    btn.className = "dur-btn" + (selectedGroups.has(name) ? " active" : "");
    btn.dataset.group = name;
    btn.style.cssText =
      "padding: 8px 16px; font-size: 12px; border-radius: 100px;";
    btn.textContent = name; // Safe — no innerHTML with user data
    btn.addEventListener("click", () => {
      const gname = btn.dataset.group;
      if (selectedGroups.has(gname)) {
        selectedGroups.delete(gname);
        btn.classList.remove("active");
      } else {
        selectedGroups.add(gname);
        btn.classList.add("active");
      }
    });
    els.sessionGroups.appendChild(btn);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  init();

});
