/**
 * ForcedFocus — Web UI Client
 * Handles countdown timer, API calls, domain management, and UI state.
 */

import { escapeHtml, formatTime, extractDomain } from "./shared/utils.js";
import { renderIntentTasks } from "./shared/intent-tasks.js";

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
let _cachedRecurring = []; // Optimistic local cache for instant UI updates

let pickerState = {
  targetInput: null,
  selectedDate: null,
  viewedDate: null,
  pickerType: 'datetime',
  hour: 12,
  minute: 0
};


// ── HTML Sanitization ────────────────────────────────────────────────────────



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
  recurringSchedulesCard: $("#recurringSchedulesCard"),
  recurringSchedulesList: $("#recurringSchedulesList"),
  recurringSchedulesCount: $("#recurringSchedulesCount"),
  recurringDays: $("#recurringDays"),
  recurringTime: $("#recurringTime"),
  btnAddRecurring: $("#btnAddRecurring"),
  rescueCard: $("#rescueCard"),
  rescueDuration: $("#rescueDuration"),
  btnRescue: $("#btnRescue"),
  sessionGroups: $("#sessionGroups"),
  permaBlockInput: $("#permaBlockInput"),
  permaBlockDomains: $("#permaBlockDomains"),
  permaBlockCount: $("#permaBlockCount"),
  permaUnblockModal: $("#permaUnblockModal"),
  permaUnblockInput: $("#permaUnblockInput"),
  permaUnblockError: $("#permaUnblockError"),
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
    const stableScheduleHash = schedules.map(s => s.start_time_iso + s.mode).join("|");
    if (stableScheduleHash !== _lastScheduleJSON) {
      _lastScheduleJSON = stableScheduleHash;
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
        if (sch.start_time_iso) {
          const startMs = new Date(sch.start_time_iso).getTime();
          calDuration.dataset.startMs = startMs;
          calDuration.textContent = "⏳ " + formatTime(Math.max(0, Math.floor((startMs - Date.now()) / 1000)));
        } else {
          calDuration.textContent = "⏳ " + String(sch.duration_minutes || 0) + " mins";
        }
        calDetails.appendChild(calTime);
        calDetails.appendChild(calTitle);
        calDetails.appendChild(calDuration);
        
        const cancelBtn = document.createElement("button");
        cancelBtn.className = "perma-cancel-btn";
        cancelBtn.textContent = "Cancel";
        cancelBtn.style.marginLeft = "auto";
        if (sch.start_time_iso) {
          const startMs = new Date(sch.start_time_iso).getTime();
          const remSecs = Math.max(0, Math.floor((startMs - Date.now()) / 1000));
          if (remSecs <= 20 * 60) {
            cancelBtn.disabled = true;
            cancelBtn.textContent = "Locked";
            cancelBtn.title = "Cannot cancel schedules within 20 minutes of starting.";
          }
        }
        cancelBtn.addEventListener("click", () => cancelSchedule(sch.start_time_iso));

        li.appendChild(calDate);
        li.appendChild(calDetails);
        li.appendChild(cancelBtn);
        els.upcomingSchedulesList.appendChild(li);
      });
    } // P2: end scheduleJSON changed block
    
    // Update live countdowns
    $$(".cal-duration").forEach(el => {
      const startMs = el.dataset.startMs;
      if (startMs) {
        const remSecs = Math.max(0, Math.floor((parseInt(startMs) - Date.now()) / 1000));
        el.textContent = "⏳ " + formatTime(remSecs);
        
        // Disable cancel button if within 20 mins
        if (remSecs <= 20 * 60) {
          const btn = el.parentElement.parentElement.querySelector(".perma-cancel-btn");
          if (btn && !btn.disabled) {
            btn.disabled = true;
            btn.textContent = "Locked";
            btn.title = "Cannot cancel schedules within 20 minutes of starting.";
          }
        }
      }
    });
  } else {
    els.upcomingSchedulesCard.classList.add("hidden");
    if (_lastScheduleJSON !== "") {
      els.upcomingSchedulesList.innerHTML = "";
      _lastScheduleJSON = "";
    }
  }

  // Update Recurring Schedules List (avoid DOM thrash if unchanged)
  const recurringSchedules = status.recurring_schedules || [];
  const recurringJSON = JSON.stringify(recurringSchedules);
  if (recurringJSON !== _lastRecurringJSON) {
    _lastRecurringJSON = recurringJSON;
    _cachedRecurring = recurringSchedules;
    renderRecurringList(_cachedRecurring);
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
          renderIntentTasks(intentTasksContainer, status.intent_tasks || [], api, status.intent);
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
    const startMs = new Date(nextSch.start_time_iso).getTime();
    const secs = Math.max(0, Math.floor((startMs - Date.now()) / 1000));

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

// ── Render Recurring Schedules List (standalone for optimistic updates) ───────

function renderRecurringList(recurring) {
  if (!els.recurringSchedulesCount) return;
  els.recurringSchedulesCount.textContent = recurring.length;
  els.recurringSchedulesList.innerHTML = "";

  if (recurring.length === 0) {
    if (els.recurringSchedulesCard) els.recurringSchedulesCard.classList.remove("hidden");
    return;
  }
  if (els.recurringSchedulesCard) els.recurringSchedulesCard.classList.remove("hidden");

  // Display order: Sat(5), Sun(6), Mon(0), Tue(1), Wed(2), Thu(3), Fri(4)
  const dayOrder = [5, 6, 0, 1, 2, 3, 4];
  const daysArr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  recurring.forEach((sch) => {
    const li = document.createElement("li");
    li.className = "recurring-item";

    const calDate = document.createElement("div");
    calDate.className = "cal-date";
    const calMonth = document.createElement("span");
    calMonth.className = "cal-month";
    calMonth.textContent = "🔁";
    calMonth.style.fontSize = "18px";
    calDate.appendChild(calMonth);

    const calDetails = document.createElement("div");
    calDetails.className = "cal-details";

    const calTime = document.createElement("div");
    calTime.className = "cal-time";
    calTime.textContent = String(sch.start_time || "");

    const calTitle = document.createElement("div");
    calTitle.className = "cal-title";
    // Sort days by Sat→Fri order for display
    const sortedDays = (sch.days_of_week || []).slice().sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b));
    const daysStr = sortedDays.map(d => daysArr[d]).join(", ");
    calTitle.textContent = daysStr;

    const calMeta = document.createElement("div");
    calMeta.className = "cal-duration";
    const modeLabel = (sch.mode === "whitelist") ? "🛡️ Whitelist" : "🚫 Blacklist";
    let typeLabel = "";
    if (sch.session_type === "pomodoro") {
      const focus = sch.focus_minutes || 25;
      const breakMin = sch.break_minutes || 5;
      const cycles = sch.cycles || 4;
      typeLabel = ` · 🍅 Pomodoro (${focus}m/${breakMin}m × ${cycles})`;
    }
    let groupsLabel = "";
    if (sch.groups && sch.groups.length > 0) {
      groupsLabel = ` · 🏷️ ${sch.groups.join(", ")}`;
    }
    calMeta.textContent = `⏳ ${sch.duration_minutes || 0}m · ${modeLabel}${typeLabel}${groupsLabel}`;

    calDetails.appendChild(calTime);
    calDetails.appendChild(calTitle);
    calDetails.appendChild(calMeta);

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "recurring-remove";
    cancelBtn.innerHTML = "×";
    cancelBtn.title = "Remove";
    cancelBtn.addEventListener("click", () => {
      if (window.removeRecurringSchedule) window.removeRecurringSchedule(sch.id);
    });

    li.appendChild(calDate);
    li.appendChild(calDetails);
    li.appendChild(cancelBtn);

    els.recurringSchedulesList.appendChild(li);
  });
}

// ── Refresh Status ───────────────────────────────────────────────────────────

// S1: Track state for detecting phase transitions
let _lastPomoPhase = null;
let _lastActiveState = null;
let _lastScheduleJSON = ""; // P2: Track schedule data to avoid DOM thrash
let _lastRecurringJSON = "";

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

  if (!domains || domains.length === 0) {
    const li = document.createElement("li");
    li.style.justifyContent = "center";
    li.style.padding = "16px";
    li.style.color = "var(--text-muted)";
    li.style.fontSize = "13px";
    li.style.fontStyle = "italic";
    li.style.background = "transparent";
    li.style.border = "1px dashed var(--border)";
    li.style.borderRadius = "8px";
    li.textContent = "No domains added yet.";
    container.appendChild(li);
    return;
  }

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

// ── Permanent Blocklist ──────────────────────────────────────────────────────

let permaCountdownInterval = null;
let permaCountdownData = {}; // domain → { remaining, el }

async function refreshPermaBlocklist() {
  const data = await api("GET", "/api/perma-blocklist");
  if (data.status !== "ok") return;

  els.permaBlockCount.textContent = (data.domains || []).length;
  renderPermaBlocklist(
    els.permaBlockDomains,
    data.domains || [],
    data.pending_unlocks || {},
  );
}

function renderPermaBlocklist(container, domains, pendingUnlocks) {
  container.innerHTML = "";
  permaCountdownData = {};

  if (!domains || domains.length === 0) {
    const li = document.createElement("li");
    li.style.justifyContent = "center";
    li.style.padding = "16px";
    li.style.color = "var(--text-muted)";
    li.style.fontSize = "13px";
    li.style.fontStyle = "italic";
    li.style.background = "transparent";
    li.style.border = "1px dashed var(--border)";
    li.style.borderRadius = "8px";
    li.textContent = "No permanently blocked domains.";
    container.appendChild(li);
    stopPermaCountdown();
    return;
  }

  let hasCountdown = false;
  domains.forEach((domain) => {
    const li = document.createElement("li");
    li.classList.add("perma-domain-item");

    const leftSpan = document.createElement("span");
    leftSpan.classList.add("perma-domain-name");

    const pending = pendingUnlocks[domain];
    if (pending && pending.remaining_seconds > 0) {
      hasCountdown = true;
      // Pending unblock state
      li.classList.add("perma-pending");

      const nameEl = document.createElement("span");
      nameEl.textContent = domain;
      leftSpan.appendChild(nameEl);

      const timerBadge = document.createElement("span");
      timerBadge.classList.add("perma-timer-badge");
      timerBadge.textContent = formatCountdown(pending.remaining_seconds);
      leftSpan.appendChild(timerBadge);

      permaCountdownData[domain] = {
        remaining: pending.remaining_seconds,
        el: timerBadge,
      };

      // Cancel unblock button
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "perma-cancel-btn";
      cancelBtn.textContent = "Cancel";
      cancelBtn.setAttribute("aria-label", `Cancel unblock for ${domain}`);
      cancelBtn.addEventListener("click", () => cancelPermaUnblock(domain));

      li.appendChild(leftSpan);
      li.appendChild(cancelBtn);
    } else {
      // Locked state
      const lockIcon = document.createElement("span");
      lockIcon.textContent = "\uD83D\uDD12";
      lockIcon.style.marginRight = "8px";
      lockIcon.style.fontSize = "11px";
      leftSpan.appendChild(lockIcon);

      const nameEl = document.createElement("span");
      nameEl.textContent = domain;
      leftSpan.appendChild(nameEl);

      // Unblock button (triggers passphrase flow)
      const removeBtn = document.createElement("button");
      removeBtn.className = "remove-btn perma-unblock-btn";
      removeBtn.textContent = "\u2715";
      removeBtn.setAttribute("aria-label", `Unblock ${domain}`);
      removeBtn.addEventListener("click", () => requestPermaUnblock(domain));

      li.appendChild(leftSpan);
      li.appendChild(removeBtn);
    }
    container.appendChild(li);
  });

  if (hasCountdown) startPermaCountdown();
  else stopPermaCountdown();
}

function formatCountdown(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

function startPermaCountdown() {
  if (permaCountdownInterval) return;
  permaCountdownInterval = setInterval(() => {
    let allDone = true;
    for (const [domain, info] of Object.entries(permaCountdownData)) {
      info.remaining = Math.max(0, info.remaining - 1);
      if (info.el) info.el.textContent = formatCountdown(info.remaining);
      if (info.remaining > 0) allDone = false;
    }
    if (allDone) {
      stopPermaCountdown();
      refreshPermaBlocklist();
    }
  }, 1000);
}

function stopPermaCountdown() {
  if (permaCountdownInterval) {
    clearInterval(permaCountdownInterval);
    permaCountdownInterval = null;
  }
}

async function addPermaBlock() {
  const input = els.permaBlockInput;
  const btn = $("#btnAddPermaBlock");
  const raw = input.value.trim();
  if (!raw) return;

  if (btn) btn.disabled = true;
  try {
    const lines = raw
      .split(/[\n\r]+/)
      .map((l) => l.trim())
      .filter(Boolean);
    const domains = [];
    const invalid = [];

    for (const line of lines) {
      const domain = extractDomain(line);
      if (/^[a-z0-9]([a-z0-9\-]*\.)+[a-z]{2,}$/.test(domain)) {
        domains.push(domain);
      } else {
        invalid.push(line);
      }
    }

    if (domains.length === 0) {
      showToast("Invalid domain. Example: tiktok.com");
      return;
    }

    if (invalid.length > 0) {
      showToast(
        `Skipped ${invalid.length} invalid: ${invalid.slice(0, 3).join(", ")}`,
      );
    }

    const res = await api("POST", "/api/perma-blocklist", {
      domains: domains,
    });
    if (res.status === "ok") {
      input.value = "";
      showToast(`\uD83D\uDD12 Permanently blocked ${domains.length} domain(s)`);
      refreshPermaBlocklist();
    } else {
      showToast("Error: " + res.message);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function requestPermaUnblock(domain) {
  const modal = els.permaUnblockModal;
  const input = els.permaUnblockInput;
  const error = els.permaUnblockError;

  modal.classList.remove("hidden");
  modal.dataset.domain = domain;
  input.value = "";
  if (error) {
    error.textContent = "";
    error.classList.add("hidden");
  }
  input.focus();
}

async function cancelPermaUnblock(domain) {
  const res = await api("POST", "/api/perma-blocklist/cancel-unblock", {
    domain,
  });
  if (res.status === "ok") {
    showToast(`\uD83D\uDD12 Re-locked ${domain}`);
    refreshPermaBlocklist();
  } else {
    showToast("Error: " + res.message);
  }
}

async function cancelSchedule(start_time_iso) {
  const res = await api("POST", "/api/cancel-schedule", { start_time_iso });
  if (res.status === "ok") {
    showToast("Schedule cancelled.");
  } else {
    showToast(`Error: ${res.message}`);
  }
}

// ── Intent Tasks ─────────────────────────────────────────────────────────────



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
        payload.schedule_at = els.scheduleAt.dataset.value || els.scheduleAt.value;
      }

      const originalBtnHTML = els.btnStart.innerHTML;
      els.btnStart.innerHTML = '<span class="btn-spinner"></span> Starting...';
      els.btnStart.disabled = true;
      els.btnStart.setAttribute("aria-busy", "true");
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
        els.btnStart.removeAttribute("aria-busy");
        isStarting = false;
      }
      refreshStatus();
    });
  }

  // Recurring Schedules Setup
  let selectedRecurringDays = [];
  
  if (els.recurringDays) {
    els.recurringDays.querySelectorAll('.day-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        btn.classList.toggle('active');
        const day = parseInt(btn.dataset.day, 10);
        if (selectedRecurringDays.includes(day)) {
          selectedRecurringDays = selectedRecurringDays.filter(d => d !== day);
        } else {
          selectedRecurringDays.push(day);
        }
      });
    });
  }

  if (els.btnAddRecurring) {
    els.btnAddRecurring.addEventListener('click', async () => {
      if (selectedRecurringDays.length === 0) {
        showToast("Please select at least one day.");
        return;
      }
      const time = els.recurringTime.dataset.value || els.recurringTime.value;
      if (!time) {
        showToast("Please select a time.");
        return;
      }

      // Derive duration from the current session settings
      let duration;
      if (sessionType === "pomodoro") {
        duration = (pomoFocusMin + pomoBreakMin) * pomoCycles;
      } else {
        duration = selectedDuration;
      }

      const payload = {
        days_of_week: selectedRecurringDays,
        start_time: time,
        duration_minutes: duration,
        mode: currentMode,
        session_type: sessionType,
        groups: Array.from(selectedGroups),
      };

      // Include pomodoro params if applicable
      if (sessionType === "pomodoro") {
        payload.focus_minutes = pomoFocusMin;
        payload.break_minutes = pomoBreakMin;
        payload.cycles = pomoCycles;
      }

      const originalBtnHTML = els.btnAddRecurring.innerHTML;
      els.btnAddRecurring.innerHTML = '<span class="btn-spinner"></span> Adding...';
      els.btnAddRecurring.disabled = true;

      try {
        const res = await api("POST", "/api/schedules/recurring", payload);
        if (res.status === "ok") {
          showToast("Recurring schedule added successfully.");
          // Optimistic: immediately render the new rule
          if (res.rule) {
            _cachedRecurring.push(res.rule);
            _lastRecurringJSON = JSON.stringify(_cachedRecurring);
            renderRecurringList(_cachedRecurring);
          }
          selectedRecurringDays = [];
          els.recurringDays.querySelectorAll('.day-btn').forEach(b => b.classList.remove('active'));
          els.recurringTime.value = "";
          delete els.recurringTime.dataset.value;
        } else {
          showToast(`Error: ${res.message || "Failed to add"}`);
        }
      } catch (err) {
        showToast("Connection failed.");
      } finally {
        els.btnAddRecurring.innerHTML = originalBtnHTML;
        els.btnAddRecurring.disabled = false;
      }
    });
  }

  window.removeRecurringSchedule = async function(id) {
    // Optimistic: immediately remove from DOM
    _cachedRecurring = _cachedRecurring.filter(r => r.id !== id);
    _lastRecurringJSON = JSON.stringify(_cachedRecurring);
    renderRecurringList(_cachedRecurring);
    try {
      const res = await api("DELETE", `/api/schedules/recurring/${id}`);
      if (res.status === "ok") {
        showToast("Recurring schedule removed.");
      } else {
        showToast(`Error: ${res.message || "Failed to remove"}`);
        // Reconcile on failure
        refreshStatus();
      }
    } catch (err) {
      showToast("Connection failed.");
      refreshStatus();
    }
  };

  // Rescue button
  els.btnRescue.addEventListener("click", async () => {
    const duration = parseInt(els.rescueDuration.value, 10) || 10;
    const payload = {
      duration: duration,
      mode: "whitelist",
      session_type: "rescue",
    };
    const originalRescueHTML = els.btnRescue.innerHTML;
    els.btnRescue.innerHTML = '<span class="btn-spinner"></span> Activating...';
    els.btnRescue.disabled = true;
    els.btnRescue.setAttribute("aria-busy", "true");
    try {
      const res = await api("POST", "/api/start", payload);
      if (res.status === "ok") {
        showToast(res.message);
        refreshStatus();
      } else {
        showToast(res.message || "Failed to activate Rescue Throne.");
      }
    } finally {
      els.btnRescue.innerHTML = originalRescueHTML;
      els.btnRescue.disabled = false;
      els.btnRescue.removeAttribute("aria-busy");
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

  // Add domain: permanent block
  $("#btnAddPermaBlock").addEventListener("click", () => addPermaBlock());
  els.permaBlockInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      addPermaBlock();
    }
  });

  // Cancel permanent unblock
  $("#btnCancelPermaUnblock").addEventListener("click", () => {
    els.permaUnblockModal.classList.add("hidden");
  });

  // Confirm permanent unblock
  $("#btnConfirmPermaUnblock").addEventListener("click", async () => {
    const domain = els.permaUnblockModal.dataset.domain;
    const key = els.permaUnblockInput.value;
    if (!key) {
      els.permaUnblockError.textContent = "Please enter your passphrase.";
      els.permaUnblockError.classList.remove("hidden");
      return;
    }

    const btn = $("#btnConfirmPermaUnblock");
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Verifying...";

    try {
      const res = await api("POST", "/api/perma-blocklist/unblock", {
        domain,
        key,
      });
      if (res.status === "pending") {
        els.permaUnblockModal.classList.add("hidden");
        showToast(`\u23F3 Unblock timer started for ${domain} (30 min)`);
        refreshPermaBlocklist();
      } else {
        els.permaUnblockError.textContent = res.message || "Invalid passphrase.";
        els.permaUnblockError.classList.remove("hidden");
      }
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });

  // Modal permanent unblock passphrase enter key
  els.permaUnblockInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("#btnConfirmPermaUnblock").click();
  });

  // Close permanent unblock modal on overlay click
  els.permaUnblockModal.addEventListener("click", (e) => {
    if (e.target === els.permaUnblockModal) els.permaUnblockModal.classList.add("hidden");
  });

  // R5: Close modal on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!els.stopModal.classList.contains("hidden")) {
        els.stopModal.classList.add("hidden");
      }
      if (!els.permaUnblockModal.classList.contains("hidden")) {
        els.permaUnblockModal.classList.add("hidden");
      }
    }
  });
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
  initPickerEvents();
  await loadApiToken();
  await refreshStatus();
  await refreshLists();
  await refreshPermaBlocklist();
  await refreshGroups();
  await loadSettings();

  // S10: Set min datetime to now, preventing past date selection
  if (els.scheduleAt) {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const minVal = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    els.scheduleAt.min = minVal;
  }

  // Modernized IPC: Server-Sent Events (SSE) instead of aggressive polling
  let eventSource = null;

  function connectSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource(API + "/api/stream");
    
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        // SSE delivers full status payloads — apply directly
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

  connectSSE();

  // P4: Pause SSE when tab is hidden to save resources
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    } else {
      refreshStatus(); // Immediate sync on return
      connectSSE();
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

// ── Custom Datetime & Time Picker Functions ───────────────────────────────────

function formatDateTimeDisplay(date) {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const m = months[date.getMonth()];
  const d = date.getDate();
  const y = date.getFullYear();
  let hrs = date.getHours();
  const mins = String(date.getMinutes()).padStart(2, "0");
  const ampm = hrs >= 12 ? "PM" : "AM";
  hrs = hrs % 12;
  hrs = hrs ? hrs : 12;
  return `${m} ${d}, ${y} at ${hrs}:${mins} ${ampm}`;
}

function formatDateTimeMachine(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatTimeDisplay(hrs, mins) {
  const pad = (n) => String(n).padStart(2, "0");
  const ampm = hrs >= 12 ? "PM" : "AM";
  let h = hrs % 12;
  h = h ? h : 12;
  return `${h}:${pad(mins)} ${ampm}`;
}

function formatTimeMachine(hrs, mins) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(hrs)}:${pad(mins)}`;
}

function closePicker() {
  const modal = document.getElementById("datetimePickerModal");
  if (modal) modal.classList.add("hidden");
}

function savePicker() {
  if (pickerState.pickerType === 'datetime') {
    if (!pickerState.selectedDate) {
      showToast("Please select a date.");
      return;
    }
    pickerState.selectedDate.setHours(pickerState.hour);
    pickerState.selectedDate.setMinutes(pickerState.minute);
    
    const now = new Date();
    if (pickerState.selectedDate <= now) {
      showToast("Please select a date and time in the future.");
      return;
    }
    
    pickerState.targetInput.value = formatDateTimeDisplay(pickerState.selectedDate);
    pickerState.targetInput.dataset.value = formatDateTimeMachine(pickerState.selectedDate);
  } else {
    pickerState.targetInput.value = formatTimeDisplay(pickerState.hour, pickerState.minute);
    pickerState.targetInput.dataset.value = formatTimeMachine(pickerState.hour, pickerState.minute);
  }
  closePicker();
}

function updatePickerPreview() {
  const preview = document.getElementById("pickerPreview");
  const hourInput = document.getElementById("pickerHour");
  const minuteInput = document.getElementById("pickerMinute");
  
  if (hourInput) hourInput.value = String(pickerState.hour).padStart(2, "0");
  if (minuteInput) minuteInput.value = String(pickerState.minute).padStart(2, "0");
  
  if (!preview) return;
  
  if (pickerState.pickerType === 'datetime') {
    if (pickerState.selectedDate) {
      pickerState.selectedDate.setHours(pickerState.hour);
      pickerState.selectedDate.setMinutes(pickerState.minute);
      preview.textContent = formatDateTimeDisplay(pickerState.selectedDate);
    } else {
      preview.textContent = "Select a date";
    }
  } else {
    preview.textContent = formatTimeDisplay(pickerState.hour, pickerState.minute);
  }
}

function renderCalendar() {
  const grid = document.getElementById("calendarDaysGrid");
  const monthYearLabel = document.getElementById("currentMonthYear");
  if (!grid || !monthYearLabel) return;
  
  grid.innerHTML = "";
  
  const year = pickerState.viewedDate.getFullYear();
  const month = pickerState.viewedDate.getMonth();
  
  const firstDay = new Date(year, month, 1);
  const startDayOfWeek = firstDay.getDay();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const prevMonthTotalDays = new Date(year, month, 0).getDate();
  
  for (let i = startDayOfWeek - 1; i >= 0; i--) {
    const dayNum = prevMonthTotalDays - i;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "calendar-day prev-month-day disabled";
    btn.disabled = true;
    btn.textContent = dayNum;
    grid.appendChild(btn);
  }
  
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  
  for (let dayNum = 1; dayNum <= totalDays; dayNum++) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "calendar-day";
    btn.textContent = dayNum;
    
    const thisDate = new Date(year, month, dayNum);
    if (pickerState.pickerType === 'datetime') {
      if (thisDate < today) {
        btn.classList.add("disabled");
        btn.disabled = true;
      }
    }
    
    if (pickerState.selectedDate &&
        pickerState.selectedDate.getDate() === dayNum &&
        pickerState.selectedDate.getMonth() === month &&
        pickerState.selectedDate.getFullYear() === year) {
      btn.classList.add("selected");
    }
    
    btn.addEventListener("click", () => {
      pickerState.selectedDate = new Date(year, month, dayNum, pickerState.hour, pickerState.minute);
      updatePickerPreview();
      renderCalendar();
    });
    
    grid.appendChild(btn);
  }
  
  const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  monthYearLabel.textContent = `${months[month]} ${year}`;
}

function openPicker(inputEl, type) {
  pickerState.targetInput = inputEl;
  pickerState.pickerType = type;
  
  const modal = document.getElementById("datetimePickerModal");
  const title = document.getElementById("pickerTitle");
  const dateSection = document.getElementById("pickerDateSection");
  
  if (!modal) return;
  
  if (title) {
    title.textContent = type === 'datetime' ? 'Select Date & Time' : 'Select Time';
  }
  
  if (dateSection) {
    dateSection.style.display = type === 'datetime' ? 'block' : 'none';
  }
  
  const val = inputEl.dataset.value;
  let initialDate = new Date();
  
  if (type === 'datetime') {
    let parsed = null;
    if (val) {
      const parts = val.split('T');
      if (parts.length === 2) {
        const dateParts = parts[0].split('-');
        const timeParts = parts[1].split(':');
        if (dateParts.length === 3 && timeParts.length === 2) {
          parsed = new Date(
            parseInt(dateParts[0]),
            parseInt(dateParts[1]) - 1,
            parseInt(dateParts[2]),
            parseInt(timeParts[0]),
            parseInt(timeParts[1])
          );
        }
      }
    }
    
    const now = new Date();
    if (!parsed || parsed <= now) {
      const d = new Date();
      d.setMinutes(d.getMinutes() + 5);
      initialDate = d;
    } else {
      initialDate = parsed;
    }
    
    pickerState.selectedDate = initialDate;
    pickerState.viewedDate = new Date(initialDate.getFullYear(), initialDate.getMonth(), 1);
    pickerState.hour = initialDate.getHours();
    pickerState.minute = initialDate.getMinutes();
    
    renderCalendar();
  } else {
    pickerState.selectedDate = null;
    pickerState.viewedDate = null;
    
    if (val) {
      const parts = val.split(':');
      if (parts.length === 2) {
        pickerState.hour = parseInt(parts[0]);
        pickerState.minute = parseInt(parts[1]);
      }
    } else {
      const now = new Date();
      pickerState.hour = now.getHours();
      pickerState.minute = now.getMinutes();
    }
  }
  
  updatePickerPreview();
  modal.classList.remove("hidden");
}

function initPickerEvents() {
  const scheduleAt = document.getElementById("scheduleAt");
  const recurringTime = document.getElementById("recurringTime");
  
  if (scheduleAt) {
    scheduleAt.addEventListener("click", () => openPicker(scheduleAt, 'datetime'));
    scheduleAt.addEventListener("focus", (e) => {
      e.target.blur();
      openPicker(scheduleAt, 'datetime');
    });
  }
  
  if (recurringTime) {
    recurringTime.addEventListener("click", () => openPicker(recurringTime, 'time'));
    recurringTime.addEventListener("focus", (e) => {
      e.target.blur();
      openPicker(recurringTime, 'time');
    });
  }
  
  const prevMonthBtn = document.getElementById("prevMonthBtn");
  const nextMonthBtn = document.getElementById("nextMonthBtn");
  
  if (prevMonthBtn) {
    prevMonthBtn.addEventListener("click", () => {
      if (pickerState.viewedDate) {
        const y = pickerState.viewedDate.getFullYear();
        const m = pickerState.viewedDate.getMonth();
        pickerState.viewedDate = new Date(y, m - 1, 1);
        renderCalendar();
      }
    });
  }
  
  if (nextMonthBtn) {
    nextMonthBtn.addEventListener("click", () => {
      if (pickerState.viewedDate) {
        const y = pickerState.viewedDate.getFullYear();
        const m = pickerState.viewedDate.getMonth();
        pickerState.viewedDate = new Date(y, m + 1, 1);
        renderCalendar();
      }
    });
  }
  
  const hourUpBtn = document.getElementById("hourUpBtn");
  const hourDownBtn = document.getElementById("hourDownBtn");
  const minuteUpBtn = document.getElementById("minuteUpBtn");
  const minuteDownBtn = document.getElementById("minuteDownBtn");
  
  if (hourUpBtn) {
    hourUpBtn.addEventListener("click", () => {
      pickerState.hour = (pickerState.hour + 1) % 24;
      updatePickerPreview();
    });
  }
  if (hourDownBtn) {
    hourDownBtn.addEventListener("click", () => {
      pickerState.hour = (pickerState.hour - 1 + 24) % 24;
      updatePickerPreview();
    });
  }
  
  if (minuteUpBtn) {
    minuteUpBtn.addEventListener("click", () => {
      pickerState.minute = (pickerState.minute + 1) % 60;
      updatePickerPreview();
    });
  }
  if (minuteDownBtn) {
    minuteDownBtn.addEventListener("click", () => {
      pickerState.minute = (pickerState.minute - 1 + 60) % 60;
      updatePickerPreview();
    });
  }
  
  const cancelPickerBtn = document.getElementById("cancelPickerBtn");
  const savePickerBtn = document.getElementById("savePickerBtn");
  const modalOverlay = document.getElementById("datetimePickerModal");
  
  if (cancelPickerBtn) {
    cancelPickerBtn.addEventListener("click", closePicker);
  }
  if (savePickerBtn) {
    savePickerBtn.addEventListener("click", savePicker);
  }
  if (modalOverlay) {
    modalOverlay.addEventListener("click", (e) => {
      if (e.target === modalOverlay) {
        closePicker();
      }
    });
  }
  
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closePicker();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  init();
});
