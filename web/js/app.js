/**
 * ForcedFocus — Web UI Client
 * Handles countdown timer, API calls, domain management, and UI state.
 */

import { escapeHtml, formatTime, extractDomain, showToast as sharedShowToast } from "../shared/utils.js";
import { api } from "../shared/api.js";
import { renderIntentTasks } from "../shared/intent-tasks.js";

const API = "";
const TIMER_CIRCUMFERENCE = 565.48; // 2 * Math.PI * 90
let currentMode = "blacklist";
let selectedDuration = 120;
let currentType = "standard";
let totalSessionSeconds = 0;
let currentRemaining = 0; // Guard against timer drift
let animationFrameId = null;
let countdownSignature = "";
let countdownRefreshTimeout = null;
let pollInterval = null;

let sessionType = "standard";
let pomoFocusMin = 25;
let pomoBreakMin = 5;
let pomoCycles = 4;

let scheduleType = "in"; // 'now', 'in', 'at'
let availableGroups = {};
let selectedGroups = new Set();
let apiToken = ""; // Per-launch API token for mutation auth
let lastActiveState = false;
let sessionSnapshot = { intent: "", tasks: [] };
let _cachedRecurring = []; // Optimistic local cache for instant UI updates
let sessionTemplates = [];
let selectedRecurringDays = [];
let editRecurringDays = [];
let editingRecurringId = null;
let editingRecurringGroups = new Set();
let trackingRange = "today";
let activeStartFlow = "now";
let trackingData = null;

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
    this._current = new Audio("/assets/sounds/" + encodeURIComponent(file));
    this._current.play().catch((e) => console.error("Audio error:", e));
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
  recurringName: $("#recurringName"),
  recurringTime: $("#recurringTime"),
  recurringSetupSummary: $("#recurringSetupSummary"),
  btnAddRecurring: $("#btnAddRecurring"),
  recurringEditModal: $("#recurringEditModal"),
  recurringEditName: $("#recurringEditName"),
  recurringEditTime: $("#recurringEditTime"),
  recurringEditDuration: $("#recurringEditDuration"),
  recurringEditMode: $("#recurringEditMode"),
  recurringEditType: $("#recurringEditType"),
  recurringEditFocus: $("#recurringEditFocus"),
  recurringEditBreak: $("#recurringEditBreak"),
  recurringEditCycles: $("#recurringEditCycles"),
  recurringEditGroups: $("#recurringEditGroups"),
  recurringEditEnabled: $("#recurringEditEnabled"),
  recurringEditDays: $("#recurringEditDays"),
  btnCancelRecurringEdit: $("#btnCancelRecurringEdit"),
  btnSaveRecurringEdit: $("#btnSaveRecurringEdit"),
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
  templatesList: $("#templatesList"),
  templatesCount: $("#templatesCount"),
  mbTemplatesList: $("#mbTemplatesList"),
  mbTemplatesCount: $("#mbTemplatesCount"),
  btnSaveTemplate: $("#btnSaveTemplate"),
  templateModal: $("#templateModal"),
  templateNameInput: $("#templateNameInput"),
  templateIntentInput: $("#templateIntentInput"),
  btnCancelTemplate: $("#btnCancelTemplate"),
  btnConfirmTemplate: $("#btnConfirmTemplate"),
  notificationFallback: $("#notificationFallback"),
  scheduleSetupSummary: $("#scheduleSetupSummary"),
};

// ── API Helpers ──────────────────────────────────────────────────────────────

const showToast = (msg, duration) => sharedShowToast(els.toast, msg, duration);

// ── Timer ────────────────────────────────────────────────────────────────────



function setTimerProgress(progress) {
  const normalized = Math.max(0, Math.min(1, Number.isFinite(progress) ? progress : 0));
  els.timerProgress.style.strokeDasharray = `${TIMER_CIRCUMFERENCE} ${TIMER_CIRCUMFERENCE}`;
  els.timerProgress.style.strokeDashoffset = TIMER_CIRCUMFERENCE * (1 - normalized);
}

function updateTimerDisplay(remMs) {
  // Update progress ring (clockwise fill).
  const totalMs = totalSessionSeconds * 1000;
  const prog = totalMs > 0 ? 1 - remMs / totalMs : 0;
  setTimerProgress(prog);
}

function scheduleCountdownRefresh() {
  if (countdownRefreshTimeout) return;
  countdownRefreshTimeout = setTimeout(() => {
    countdownRefreshTimeout = null;
    refreshStatus();
  }, 150);
}

function cancelCountdownFrame() {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
}

function startCountdown(remainingSeconds, signature = "timer") {
  const normalizedRemaining = Math.max(0, Number(remainingSeconds) || 0);
  const normalizedTotal = Math.max(0, Number(totalSessionSeconds) || 0);
  const nextSignature = `${signature}:${normalizedTotal}`;
  if (
    animationFrameId &&
    countdownSignature === nextSignature &&
    Math.abs(currentRemaining - normalizedRemaining) <= 2
  ) {
    return;
  }
  cancelCountdownFrame();
  countdownSignature = nextSignature;

  const startTime = performance.now();
  const durationMs = normalizedRemaining * 1000;
  const endTime = startTime + durationMs;
  currentRemaining = normalizedRemaining;

  let lastSecs = -1;

  const tick = () => {
    const now = performance.now();
    const remMs = endTime - now;

    if (remMs <= 0) {
      animationFrameId = null;
      countdownSignature = "";
      currentRemaining = 0;
      els.timerValue.textContent = formatTime(0);
      updateTimerDisplay(0);
      scheduleCountdownRefresh();
      return;
    }

    const remSecs = Math.ceil(remMs / 1000);
    currentRemaining = remSecs;
    
    // Only update text when second changes
    if (remSecs !== lastSecs) {
      els.timerValue.textContent = formatTime(remSecs);
      lastSecs = remSecs;
    }
    
    updateTimerDisplay(remMs);
    animationFrameId = requestAnimationFrame(tick);
  };

  tick();
}

function stopCountdown() {
  cancelCountdownFrame();
  countdownSignature = "";
  currentRemaining = 0;
  if (countdownRefreshTimeout) {
    clearTimeout(countdownRefreshTimeout);
    countdownRefreshTimeout = null;
  }
  setTimerProgress(0);
}

let isStarting = false;
let isSessionActive = false;

function ensureSessionHint(card, text) {
  if (!card) return null;
  let hint = card.querySelector(".session-next-hint");
  if (!hint) {
    hint = document.createElement("div");
    hint.className = "session-next-hint hidden";
    card.appendChild(hint);
  }
  hint.textContent = text;
  return hint;
}

function setActiveControlAvailability(isFullyActive) {
  isSessionActive = Boolean(isFullyActive);

  [els.modeCard, els.sessionSettingsCard, els.scheduleCard, els.rescueCard].forEach((card) => {
    if (card) card.classList.remove("disabled");
  });

  const modeHint = ensureSessionHint(els.modeCard, "Changes here apply to your next focus session.");
  const settingsHint = ensureSessionHint(els.sessionSettingsCard, "Duration and Pomodoro edits apply to the next session.");
  const scheduleHint = ensureSessionHint(els.scheduleCard, "You can still prepare future schedules while focusing.");
  const rescueHint = ensureSessionHint(els.rescueCard, "Rescue can only start when no focus session is active.");

  [modeHint, settingsHint, scheduleHint, rescueHint].forEach((hint) => {
    if (hint) hint.classList.toggle("hidden", !isFullyActive);
  });

  if (els.rescueCard) els.rescueCard.classList.toggle("active-session-limited", isFullyActive);
  if (els.btnRescue) {
    els.btnRescue.disabled = isFullyActive;
    els.btnRescue.setAttribute(
      "title",
      isFullyActive ? "Finish or request unlock before starting Rescue." : "Activate Rescue",
    );
  }
}

function renderNotificationFallback(warning) {
  if (!els.notificationFallback) return;
  if (!warning || !warning.message) {
    els.notificationFallback.classList.add("hidden");
    els.notificationFallback.textContent = "";
    return;
  }
  els.notificationFallback.textContent = warning.message;
  els.notificationFallback.classList.remove("hidden");
}

// ── UI State ─────────────────────────────────────────────────────────────────

function setActiveUI(status) {
  if (isStarting) return;
  renderNotificationFallback(status.notification_warning);

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

  setActiveControlAvailability(isFullyActive);

  // Start/stop buttons
  els.btnStart.classList.toggle("hidden", isFullyActive);
  els.btnStop.classList.toggle("hidden", !isFullyActive);
  
  const btnScheduleAdd = document.getElementById("btnScheduleAdd");
  if (btnScheduleAdd) {
    if (scheduleType === "now") {
      btnScheduleAdd.textContent = isFullyActive ? "Merge with Active" : "Start Session";
    } else {
      btnScheduleAdd.textContent = "Add Schedule";
    }
  }

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
    updateLiveCountdowns();
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
      startCountdown(
        status.pomo_phase_remaining || 0,
        `pomo:${status.pomo_phase}:${status.pomo_current_cycle || 0}`,
      );
    } else {
      els.pomoStatus.classList.add("hidden");
      els.timerRing.classList.remove("break");
      els.timerLabel.textContent = "REMAINING";

      totalSessionSeconds =
        status.total_duration_seconds || status.remaining_seconds;
      startCountdown(
        status.remaining_seconds,
        `active:${status.session_type || "standard"}:${status.expires_at || ""}`,
      );
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
      startCountdown(secs, `scheduled:${nextSch.start_time_iso || ""}`);
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

// ── Recurring Schedules UI ───────────────────────────────────────────────────

const recurringDayOrder = [5, 6, 0, 1, 2, 3, 4];
const recurringDayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function sortedRecurringDays(days = []) {
  return days
    .slice()
    .sort((a, b) => recurringDayOrder.indexOf(a) - recurringDayOrder.indexOf(b));
}

function formatRecurringDayList(days = []) {
  const sortedDays = sortedRecurringDays(days);
  if (sortedDays.length === 7) return "Every day";
  if (sortedDays.length === 0) return "No days";
  return sortedDays.map((day) => recurringDayLabels[day] || "").filter(Boolean).join(", ");
}

function modeLabel(mode) {
  return mode === "whitelist" ? "Whitelist" : "Blacklist";
}

function typeLabel(type) {
  if (type === "pomodoro") return "Pomodoro";
  if (type === "rescue") return "Rescue";
  return "Standard";
}

function currentRecurringDuration() {
  if (sessionType === "pomodoro") {
    return (pomoFocusMin + pomoBreakMin) * pomoCycles;
  }
  return selectedDuration;
}

function updateRecurringSetupSummary() {
  if (!els.recurringSetupSummary) return;
  const daysText = selectedRecurringDays.length ? formatRecurringDayList(selectedRecurringDays) : "Choose days";
  const timeText = els.recurringTime?.dataset.value || els.recurringTime?.value || "Choose time";
  const groups = Array.from(selectedGroups);
  const groupText = groups.length ? groups.join(", ") : "No groups";
  const details = [
    `${daysText} at ${timeText}`,
    `${currentRecurringDuration()}m`,
    modeLabel(currentMode),
    typeLabel(sessionType),
    groupText,
  ];
  els.recurringSetupSummary.textContent = details.join(" · ");
}

function updateScheduleSetupSummary() {
  if (!els.scheduleSetupSummary) return;
  const tempFlow = activeStartFlow; 
  activeStartFlow = scheduleType; // force it so computeBlockDetails sees the correct schedule type
  const details = computeBlockDetails();
  activeStartFlow = tempFlow;
  
  els.scheduleSetupSummary.textContent = `${details.sessionType} · ${details.blockType} · ${details.durationText} · ${details.groupText} · ${details.expiryText}`;
}

function updateSetupSummaries() {
  updateRecurringSetupSummary();
  updateScheduleSetupSummary();
}

function setRecurringDayButtons(container, selectedDays) {
  if (!container) return;
  container.querySelectorAll(".day-btn").forEach((btn) => {
    const day = parseInt(btn.dataset.day, 10);
    btn.classList.toggle("active", selectedDays.includes(day));
  });
}

function createRecurringChip(text, className = "") {
  const chip = document.createElement("span");
  chip.className = `recurring-chip${className ? ` ${className}` : ""}`;
  chip.textContent = text;
  return chip;
}

function buildRecurringPayloadFromCurrent() {
  const payload = {
    name: els.recurringName?.value.trim() || "Focus Ritual",
    days_of_week: selectedRecurringDays,
    start_time: els.recurringTime.dataset.value || els.recurringTime.value,
    duration_minutes: currentRecurringDuration(),
    mode: currentMode,
    session_type: sessionType,
    groups: Array.from(selectedGroups),
  };

  if (sessionType === "pomodoro") {
    payload.focus_minutes = pomoFocusMin;
    payload.break_minutes = pomoBreakMin;
    payload.cycles = pomoCycles;
  }

  return payload;
}

function renderRecurringList(recurring) {
  if (!els.recurringSchedulesCount) return;
  els.recurringSchedulesCount.textContent = recurring.length;
  els.recurringSchedulesList.innerHTML = "";

  if (recurring.length === 0) {
    if (els.recurringSchedulesCard) els.recurringSchedulesCard.classList.remove("hidden");
    const empty = document.createElement("li");
    empty.className = "empty-list";
    empty.textContent = "No recurring focus rituals yet.";
    els.recurringSchedulesList.appendChild(empty);
    return;
  }
  if (els.recurringSchedulesCard) els.recurringSchedulesCard.classList.remove("hidden");

  recurring.forEach((sch) => {
    const li = document.createElement("li");
    li.className = `recurring-item${sch.enabled === false ? " paused" : ""}`;

    const calDetails = document.createElement("div");
    calDetails.className = "cal-details";

    const top = document.createElement("div");
    top.className = "recurring-rule-top";

    const name = document.createElement("div");
    name.className = "recurring-rule-name";
    name.textContent = sch.name || "Focus Ritual";

    const state = document.createElement("span");
    state.className = `recurring-state-badge${sch.enabled === false ? " paused" : ""}`;
    state.textContent = sch.enabled === false ? "Paused" : "Active";

    top.appendChild(name);
    top.appendChild(state);

    const dayChips = document.createElement("div");
    dayChips.className = "recurring-day-chips";
    sortedRecurringDays(sch.days_of_week || []).forEach((day) => {
      dayChips.appendChild(createRecurringChip(recurringDayLabels[day], "day-active"));
    });

    const metaChips = document.createElement("div");
    metaChips.className = "recurring-meta-chips";
    metaChips.appendChild(createRecurringChip(`Next: ${sch.next_run_label || "Paused"}`));
    metaChips.appendChild(createRecurringChip(`Time: ${sch.start_time || "--:--"}`));
    metaChips.appendChild(createRecurringChip(`${sch.duration_minutes || 0}m`));
    metaChips.appendChild(createRecurringChip(modeLabel(sch.mode)));
    metaChips.appendChild(createRecurringChip(typeLabel(sch.session_type)));
    if (sch.session_type === "pomodoro") {
      metaChips.appendChild(createRecurringChip(`${sch.focus_minutes || 25}/${sch.break_minutes || 5} x ${sch.cycles || 4}`));
    }
    if (sch.groups && sch.groups.length) {
      metaChips.appendChild(createRecurringChip(sch.groups.join(", ")));
    }
    if (sch.last_result) {
      metaChips.appendChild(createRecurringChip(`Last: ${sch.last_result}`));
    }

    calDetails.appendChild(top);
    calDetails.appendChild(dayChips);
    calDetails.appendChild(metaChips);

    const actions = document.createElement("div");
    actions.className = "recurring-actions";

    let isLocked = false;
    if (sch.enabled !== false && sch.next_run_at) {
      const nextRunDate = new Date(sch.next_run_at);
      const diffMinutes = (nextRunDate.getTime() - Date.now()) / 60000;
      if (diffMinutes <= 20 && diffMinutes > -5) {
        isLocked = true;
      }
    }

    if (isLocked) {
      const lockedBtn = document.createElement("button");
      lockedBtn.className = "recurring-action";
      lockedBtn.textContent = "🔒 Locked";
      lockedBtn.disabled = true;
      lockedBtn.style.cursor = "not-allowed";
      lockedBtn.style.opacity = "0.7";
      lockedBtn.style.color = "var(--text-muted)";
      actions.appendChild(lockedBtn);
    } else {
      const toggleBtn = document.createElement("button");
      toggleBtn.className = "recurring-action";
      toggleBtn.textContent = sch.enabled === false ? "Resume" : "Pause";
      toggleBtn.setAttribute("aria-label", `${toggleBtn.textContent} ${sch.name || "recurring schedule"}`);
      toggleBtn.addEventListener("click", () => toggleRecurringSchedule(sch.id, sch.enabled === false));

      const editBtn = document.createElement("button");
      editBtn.className = "recurring-action";
      editBtn.textContent = "Edit";
      editBtn.setAttribute("aria-label", `Edit ${sch.name || "recurring schedule"}`);
      editBtn.addEventListener("click", () => openRecurringEditModal(sch));

      const duplicateBtn = document.createElement("button");
      duplicateBtn.className = "recurring-action";
      duplicateBtn.textContent = "Duplicate";
      duplicateBtn.setAttribute("aria-label", `Duplicate ${sch.name || "recurring schedule"}`);
      duplicateBtn.addEventListener("click", () => duplicateRecurringSchedule(sch.id));

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "recurring-action danger";
      deleteBtn.textContent = "Delete";
      deleteBtn.setAttribute("aria-label", `Delete ${sch.name || "recurring schedule"}`);
      deleteBtn.addEventListener("click", () => removeRecurringSchedule(sch.id));

      actions.appendChild(toggleBtn);
      actions.appendChild(editBtn);
      actions.appendChild(duplicateBtn);
      actions.appendChild(deleteBtn);
    }

    li.appendChild(calDetails);
    li.appendChild(actions);

    els.recurringSchedulesList.appendChild(li);
  });
}

function syncRecurringCache(rule) {
  const index = _cachedRecurring.findIndex((item) => item.id === rule.id);
  if (index >= 0) {
    _cachedRecurring[index] = rule;
  } else {
    _cachedRecurring.push(rule);
  }
  _lastRecurringJSON = JSON.stringify(_cachedRecurring);
  renderRecurringList(_cachedRecurring);
}

async function toggleRecurringSchedule(id, shouldEnable) {
  const endpoint = shouldEnable ? "resume" : "pause";
  const res = await api("POST", `/api/schedules/recurring/${encodeURIComponent(id)}/${endpoint}`, {});
  if (res.status === "ok") {
    if (res.rule) syncRecurringCache(res.rule);
    showToast(shouldEnable ? "Recurring schedule resumed." : "Recurring schedule paused.");
    await refreshStatus();
  } else {
    showToast(`Error: ${res.message || "Failed to update schedule"}`);
    refreshStatus();
  }
}

async function duplicateRecurringSchedule(id) {
  const res = await api("POST", `/api/schedules/recurring/${encodeURIComponent(id)}/duplicate`, {});
  if (res.status === "ok") {
    if (res.rule) syncRecurringCache(res.rule);
    showToast("Recurring schedule duplicated.");
    await refreshStatus();
  } else {
    showToast(`Error: ${res.message || "Failed to duplicate schedule"}`);
    refreshStatus();
  }
}

async function removeRecurringSchedule(id) {
  const previous = _cachedRecurring.slice();
  _cachedRecurring = _cachedRecurring.filter((rule) => rule.id !== id);
  _lastRecurringJSON = JSON.stringify(_cachedRecurring);
  renderRecurringList(_cachedRecurring);
  try {
    const res = await api("DELETE", `/api/schedules/recurring/${encodeURIComponent(id)}`);
    if (res.status === "ok") {
      showToast("Recurring schedule removed.");
      await refreshStatus();
    } else {
      _cachedRecurring = previous;
      _lastRecurringJSON = JSON.stringify(_cachedRecurring);
      renderRecurringList(_cachedRecurring);
      showToast(`Error: ${res.message || "Failed to remove"}`);
    }
  } catch (err) {
    _cachedRecurring = previous;
    _lastRecurringJSON = JSON.stringify(_cachedRecurring);
    renderRecurringList(_cachedRecurring);
    showToast("Connection failed.");
  }
}

function updateEditModalFields() {
  const type = els.recurringEditType?.value || "standard";
  const durationField = document.getElementById("recurringEditDurationField");
  const modeField = document.getElementById("recurringEditModeField");
  const focusField = document.getElementById("recurringEditFocusField");
  const breakField = document.getElementById("recurringEditBreakField");
  const cyclesField = document.getElementById("recurringEditCyclesField");

  if (type === "pomodoro") {
    if (durationField) durationField.classList.add("hidden");
    if (modeField) modeField.classList.remove("hidden");
    if (focusField) focusField.classList.remove("hidden");
    if (breakField) breakField.classList.remove("hidden");
    if (cyclesField) cyclesField.classList.remove("hidden");
  } else if (type === "rescue") {
    if (durationField) durationField.classList.remove("hidden");
    if (modeField) modeField.classList.add("hidden");
    if (focusField) focusField.classList.add("hidden");
    if (breakField) breakField.classList.add("hidden");
    if (cyclesField) cyclesField.classList.add("hidden");
    if (els.recurringEditMode) els.recurringEditMode.value = "whitelist";
  } else {
    // standard
    if (durationField) durationField.classList.remove("hidden");
    if (modeField) modeField.classList.remove("hidden");
    if (focusField) focusField.classList.add("hidden");
    if (breakField) breakField.classList.add("hidden");
    if (cyclesField) cyclesField.classList.add("hidden");
  }
}

function renderRecurringEditGroups() {
  if (!els.recurringEditGroups) return;
  
  if (Object.keys(availableGroups).length === 0) {
    els.recurringEditGroups.replaceChildren();
    const emptyMsg = document.createElement("div");
    emptyMsg.className = "loading-muted";
    emptyMsg.textContent = "No groups configured.";
    els.recurringEditGroups.appendChild(emptyMsg);
    return;
  }

  els.recurringEditGroups.innerHTML = "";
  for (const name of Object.keys(availableGroups)) {
    const btn = document.createElement("button");
    btn.className = "dur-btn group-chip" + (editingRecurringGroups.has(name) ? " active" : "");
    btn.dataset.group = name;
    btn.textContent = name;
    btn.addEventListener("click", () => {
      if (editingRecurringGroups.has(name)) {
        editingRecurringGroups.delete(name);
        btn.classList.remove("active");
      } else {
        editingRecurringGroups.add(name);
        btn.classList.add("active");
      }
    });
    els.recurringEditGroups.appendChild(btn);
  }
}

function openRecurringEditModal(rule) {
  if (!els.recurringEditModal) return;
  editingRecurringId = rule.id;
  editRecurringDays = (rule.days_of_week || []).slice();
  els.recurringEditName.value = rule.name || "Focus Ritual";
  
  const startTime = rule.start_time || "";
  els.recurringEditTime.value = startTime ? convertToDisplayTime(startTime) : "";
  els.recurringEditTime.dataset.value = startTime;

  els.recurringEditDuration.value = rule.duration_minutes || 120;
  els.recurringEditMode.value = rule.mode || "blacklist";
  els.recurringEditType.value = rule.session_type || "standard";
  els.recurringEditFocus.value = rule.focus_minutes || 25;
  els.recurringEditBreak.value = rule.break_minutes || 5;
  els.recurringEditCycles.value = rule.cycles || 4;
  
  editingRecurringGroups = new Set(rule.groups || []);
  renderRecurringEditGroups();
  els.recurringEditEnabled.checked = rule.enabled !== false;
  
  setRecurringDayButtons(els.recurringEditDays, editRecurringDays);
  updateEditModalFields();

  els.recurringEditModal.classList.remove("hidden");
  els.recurringEditName.focus();
}

function closeRecurringEditModal() {
  editingRecurringId = null;
  editRecurringDays = [];
  editingRecurringGroups.clear();
  if (els.recurringEditModal) els.recurringEditModal.classList.add("hidden");
}

async function saveRecurringEdit() {
  if (!editingRecurringId) return;
  if (editRecurringDays.length === 0) {
    showToast("Please select at least one day.");
    return;
  }
  const startTime = (els.recurringEditTime.dataset.value || els.recurringEditTime.value || "").trim();
  if (!/^\d{1,2}:\d{2}$/.test(startTime)) {
    showToast("Please use HH:MM time.");
    return;
  }

  const type = els.recurringEditType.value;
  let duration = parseInt(els.recurringEditDuration.value, 10) || 120;
  const focus = parseInt(els.recurringEditFocus.value, 10) || 25;
  const breakTime = parseInt(els.recurringEditBreak.value, 10) || 5;
  const cycles = parseInt(els.recurringEditCycles.value, 10) || 4;

  if (type === "pomodoro") {
    duration = (focus + breakTime) * cycles;
  }

  const groups = Array.from(editingRecurringGroups);
  const payload = {
    name: els.recurringEditName.value.trim() || "Focus Ritual",
    days_of_week: editRecurringDays,
    start_time: startTime,
    duration_minutes: duration,
    mode: type === "rescue" ? "whitelist" : els.recurringEditMode.value,
    session_type: type,
    focus_minutes: focus,
    break_minutes: breakTime,
    cycles: cycles,
    groups,
    enabled: els.recurringEditEnabled.checked,
  };

  const originalText = els.btnSaveRecurringEdit.textContent;
  els.btnSaveRecurringEdit.textContent = "Saving...";
  els.btnSaveRecurringEdit.disabled = true;
  try {
    const res = await api("POST", `/api/schedules/recurring/${encodeURIComponent(editingRecurringId)}`, payload);
    if (res.status === "ok") {
      if (res.rule) syncRecurringCache(res.rule);
      closeRecurringEditModal();
      showToast("Recurring schedule updated.");
      await refreshStatus();
    } else {
      showToast(`Error: ${res.message || "Failed to update schedule"}`);
    }
  } catch (err) {
    showToast("Connection failed.");
  } finally {
    els.btnSaveRecurringEdit.textContent = originalText;
    els.btnSaveRecurringEdit.disabled = false;
  }
}

// ── Smart Session Templates ──────────────────────────────────────────────────

function currentSessionTemplatePayload(name, intent = "") {
  let duration = selectedDuration;
  const payload = {
    name,
    mode: currentMode,
    session_type: sessionType,
    duration_minutes: duration,
    groups: Array.from(selectedGroups),
    intent,
    intent_tasks: [],
  };

  if (sessionType === "pomodoro") {
    duration = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    payload.duration_minutes = duration;
    payload.focus_minutes = pomoFocusMin;
    payload.break_minutes = pomoBreakMin;
    payload.cycles = pomoCycles;
  }

  return payload;
}

function templateDurationLabel(template) {
  if (template.session_type === "pomodoro") {
    return `${template.focus_minutes || 25}/${template.break_minutes || 5} × ${template.cycles || 4}`;
  }
  return `${template.duration_minutes || 0}m`;
}

async function refreshTemplates() {
  if (!els.templatesList) return;
  const data = await api("GET", "/api/templates");
  if (data.status !== "ok") return;
  sessionTemplates = data.templates || [];
  renderTemplates();
}

function renderTemplates() {
  if (els.templatesList) {
    els.templatesCount.textContent = sessionTemplates.length;
    els.templatesList.innerHTML = "";
  }
  if (els.mbTemplatesList) {
    els.mbTemplatesCount.textContent = sessionTemplates.length;
    els.mbTemplatesList.innerHTML = "";
  }

  if (sessionTemplates.length === 0) {
    if (els.templatesList) {
      const empty = document.createElement("div");
      empty.className = "empty-list";
      empty.textContent = "No templates saved yet.";
      els.templatesList.appendChild(empty);
    }
    if (els.mbTemplatesList) {
      const emptyMb = document.createElement("div");
      emptyMb.className = "empty-list";
      emptyMb.style.cssText = "font-size: 11px; color: #71717a; text-align: center; padding: 4px 0;";
      emptyMb.textContent = "No templates saved";
      els.mbTemplatesList.appendChild(emptyMb);
    }
    return;
  }

  sessionTemplates.forEach((template) => {
    if (els.templatesList) {
      const item = document.createElement("div");
      item.className = "template-item";

      const main = document.createElement("div");
      const name = document.createElement("div");
      name.className = "template-name";
      name.textContent = template.name || "Untitled";
      const meta = document.createElement("div");
      meta.className = "template-meta";

      const chips = [
        template.mode === "whitelist" ? "Whitelist" : "Blacklist",
        template.session_type === "rescue" ? "Rescue" : template.session_type === "pomodoro" ? "Pomodoro" : "Standard",
        templateDurationLabel(template),
        (template.groups || []).length ? `Groups: ${(template.groups || []).join(", ")}` : "No groups",
        `${template.use_count || 0} uses`,
      ];
      chips.forEach((value) => {
        const chip = document.createElement("span");
        chip.className = "template-chip";
        chip.textContent = value;
        meta.appendChild(chip);
      });
      main.appendChild(name);
      main.appendChild(meta);

      const buttons = document.createElement("div");
      buttons.className = "template-buttons";

      const startBtn = document.createElement("button");
      startBtn.className = "template-start";
      startBtn.textContent = "Start";
      startBtn.setAttribute("aria-label", `Start ${template.name || "template"}`);
      startBtn.addEventListener("click", () => startTemplate(template.id, startBtn));

      const duplicateBtn = document.createElement("button");
      duplicateBtn.textContent = "Duplicate";
      duplicateBtn.setAttribute("aria-label", `Duplicate ${template.name || "template"}`);
      duplicateBtn.addEventListener("click", () => duplicateTemplate(template.id));

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "template-delete";
      deleteBtn.textContent = "Delete";
      deleteBtn.setAttribute("aria-label", `Delete ${template.name || "template"}`);
      deleteBtn.addEventListener("click", () => deleteTemplate(template.id));

      buttons.appendChild(startBtn);
      buttons.appendChild(duplicateBtn);
      buttons.appendChild(deleteBtn);

      item.appendChild(main);
      item.appendChild(buttons);
      els.templatesList.appendChild(item);
    }

    if (els.mbTemplatesList) {
      const mbItem = document.createElement("div");
      mbItem.style.cssText = "display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.05); padding: 8px 10px; border-radius: 6px; cursor: pointer; transition: background 0.2s;";
      
      const leftCol = document.createElement("div");
      leftCol.style.cssText = "display: flex; flex-direction: column; gap: 2px;";
      
      const title = document.createElement("div");
      title.style.cssText = "font-size: 12px; font-weight: 500; color: #fff;";
      title.textContent = template.name || "Untitled";
      
      const meta = document.createElement("div");
      meta.style.cssText = "font-size: 10px; color: #a1a1aa;";
      meta.textContent = `${templateDurationLabel(template)} • ${template.mode === "whitelist" ? "WL" : "BL"}`;
      
      leftCol.appendChild(title);
      leftCol.appendChild(meta);
      
      const startBtn = document.createElement("button");
      startBtn.textContent = "▶";
      startBtn.style.cssText = "background: rgba(255,255,255,0.1); border: none; color: white; width: 24px; height: 24px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 10px;";
      
      mbItem.addEventListener("mouseenter", () => { mbItem.style.background = "rgba(255,255,255,0.1)"; startBtn.style.background = "var(--primary)"; });
      mbItem.addEventListener("mouseleave", () => { mbItem.style.background = "rgba(255,255,255,0.05)"; startBtn.style.background = "rgba(255,255,255,0.1)"; });
      
      mbItem.addEventListener("click", () => {
        startBtn.textContent = "⌛";
        startTemplate(template.id, startBtn);
      });
      
      mbItem.appendChild(leftCol);
      mbItem.appendChild(startBtn);
      els.mbTemplatesList.appendChild(mbItem);
    }
  });
}

async function saveTemplateFromCurrent() {
  const name = els.templateNameInput.value.trim();
  if (!name) {
    showToast("Template name is required.");
    return;
  }
  const payload = currentSessionTemplatePayload(name, els.templateIntentInput.value.trim());
  els.btnConfirmTemplate.disabled = true;
  try {
    const res = await api("POST", "/api/templates", payload);
    if (res.status === "ok") {
      els.templateModal.classList.add("hidden");
      showToast("Template saved.");
      await refreshTemplates();
    } else {
      showToast(`Error: ${res.message || "Failed to save template"}`);
    }
  } finally {
    els.btnConfirmTemplate.disabled = false;
  }
}

function startTemplate(templateId, button) {
  const template = sessionTemplates.find(t => t.id === templateId);
  if (!template) return;

  // 1. Set Mode
  currentMode = template.mode || "blacklist";
  $$(".mode-btn:not(.session-type-btn):not(.schedule-type-btn)").forEach(b => b.classList.remove("active"));
  const modeBtn = $(`#btn${currentMode === "whitelist" ? "Whitelist" : "Blacklist"}`);
  if (modeBtn) modeBtn.classList.add("active");

  // 2. Set Session Type
  sessionType = template.session_type || "standard";
  $$(".session-type-btn").forEach((b) => b.classList.remove("active"));
  const typeBtn = $(`.session-type-btn[data-type="${sessionType}"]`);
  if (typeBtn) typeBtn.classList.add("active");

  if (sessionType === "pomodoro") {
    els.standardSettingsArea.classList.add("hidden");
    els.pomodoroSettingsArea.classList.remove("hidden");
    els.sessionSettingsTitle.textContent = "🍅 Pomodoro Settings";
    
    els.pomoFocus.value = template.focus_minutes || 25;
    els.pomoBreak.value = template.break_minutes || 5;
    els.pomoCycles.value = template.cycles || 4;
    $$(".pomo-preset").forEach((b) => b.classList.remove("active"));
    pomoFocusMin = parseInt(els.pomoFocus.value) || 25;
    pomoBreakMin = parseInt(els.pomoBreak.value) || 5;
    pomoCycles = parseInt(els.pomoCycles.value) || 4;
    
    const total = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    const h = Math.floor(total / 60);
    const m = total % 60;
    els.pomoSummary.textContent = `Total: ${h}h ${String(m).padStart(2, "0")}m (${pomoCycles} × ${pomoFocusMin}m focus + ${pomoBreakMin}m break)`;
  } else if (sessionType === "rescue") {
    els.rescueDuration.value = template.duration_minutes || 10;
  } else {
    els.standardSettingsArea.classList.remove("hidden");
    els.pomodoroSettingsArea.classList.add("hidden");
    els.sessionSettingsTitle.textContent = "Session Duration";

    selectedDuration = template.duration_minutes || 120;
    $$(".dur-btn:not(.pomo-preset)").forEach((b) => b.classList.remove("active"));
    const durBtn = $(`.dur-btn:not(.pomo-preset)[data-minutes="${selectedDuration}"]`);
    if (durBtn) {
      durBtn.classList.add("active");
      els.customMinutes.value = "";
    } else {
      els.customMinutes.value = selectedDuration;
    }
  }

  // 3. Set Groups
  selectedGroups.clear();
  if (template.groups && template.groups.length) {
    template.groups.forEach(g => selectedGroups.add(g));
  }
  renderSessionGroups();
  
  // 4. Prefill Intent if any
  const intentInput = document.getElementById("intentModalInput");
  if (intentInput) {
    intentInput.value = template.intent || "";
  }
  const intentTasksInput = document.getElementById("intentTasksInput");
  if (intentTasksInput) {
    intentTasksInput.value = (template.intent_tasks || []).join("\n");
  }

  if (typeof updateSetupSummaries === 'function') {
    updateSetupSummaries();
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (sessionType === "rescue") {
    if (els.btnRescue) els.btnRescue.focus();
    showToast("Rescue template loaded. Click 'Activate Rescue' to begin.");
  } else {
    if (els.btnStart) els.btnStart.focus();
    showToast("Template loaded. Click 'Start Blocking' to begin.");
  }
}

async function duplicateTemplate(templateId) {
  const res = await api("POST", `/api/templates/${encodeURIComponent(templateId)}/duplicate`, {});
  if (res.status === "ok") {
    showToast("Template duplicated.");
    await refreshTemplates();
  } else {
    showToast(`Error: ${res.message || "Failed to duplicate template"}`);
  }
}

async function deleteTemplate(templateId) {
  const res = await api("DELETE", `/api/templates/${encodeURIComponent(templateId)}`);
  if (res.status === "ok") {
    showToast("Template deleted.");
    await refreshTemplates();
  } else {
    showToast(`Error: ${res.message || "Failed to delete template"}`);
  }
}

// ── Refresh Status ───────────────────────────────────────────────────────────

// S1: Track state for detecting phase transitions
let _lastPomoPhase = null;
let _lastActiveState = null;
let _lastRevision = undefined;
let _lastScheduleJSON = ""; // P2: Track schedule data to avoid DOM thrash
let _lastRecurringJSON = "";

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sessionStatusMatchesPayload(status, payload) {
  if (!status || status.status !== "ok") return false;
  const expectedType = payload.session_type || "standard";
  const scheduled = Boolean(payload.schedule_in || payload.schedule_at);
  if (scheduled) {
    return (status.schedules || []).some(
      (schedule) =>
        schedule.cmd &&
        schedule.cmd.mode === payload.mode &&
        schedule.cmd.session_type === expectedType,
    );
  }
  return (
    status.active === true &&
    status.mode === payload.mode &&
    status.session_type === expectedType
  );
}

function stopStatusConfirmed(status) {
  return (
    status &&
    status.status === "ok" &&
    (status.active === false || Boolean(status.pending_unlock))
  );
}

async function waitForStatusConfirmation(predicate, attempts = 5, delayMs = 200) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const status = await api("GET", "/api/status");
    if (predicate(status)) {
      setActiveUI(status);
      return status;
    }
    if (attempt < attempts - 1) await delay(delayMs);
  }
  return null;
}

async function refreshStatus() {
  const data = await api("GET", "/api/status");
  if (data.status === "ok") {
    // S1: Detect phase transitions that require timer reset
    const phaseChanged = data.pomo_phase !== _lastPomoPhase;
    const activeChanged = data.active !== _lastActiveState;
    if (phaseChanged || activeChanged) {
      cancelCountdownFrame();
      countdownSignature = "";
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
    li.className = "empty-list-item";
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
    li.className = "empty-list-item";
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
      lockIcon.className = "perma-lock-icon";
      lockIcon.textContent = "\uD83D\uDD12";
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

// ── Block Details ────────────────────────────────────────────────────────────

/**
 * Compute session configuration preview from current local state.
 * Handles standard, pomodoro, and scheduled session types.
 * @returns {{ blockType: string, sessionType: string, durationText: string, expiryText: string, domainCount: string }}
 */
function computeBlockDetails() {
  const blockType = currentMode === "whitelist" ? "✅ Whitelist" : "🚫 Blacklist";
  const sessionLabel = sessionType === "pomodoro" ? "🍅 Pomodoro" : "⏱ Standard";

  let totalMinutes;
  let durationText;
  if (sessionType === "pomodoro") {
    totalMinutes = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    durationText = `${pomoFocusMin}m focus × ${pomoCycles} cycles`;
  } else {
    totalMinutes = selectedDuration;
    const hrs = Math.floor(selectedDuration / 60);
    const mins = selectedDuration % 60;
    durationText = hrs > 0 ? `${hrs}h ${mins > 0 ? mins + "m" : ""}`.trim() : `${mins}m`;
  }

  // Compute expiry based on schedule type
  let expiryText;
  if (activeStartFlow === "at") {
    const atVal = els.scheduleAt?.dataset?.value;
    expiryText = atVal ? `Scheduled: ${els.scheduleAt.value}` : "—";
  } else if (activeStartFlow === "in") {
    const inMin = parseInt(els.scheduleIn?.value, 10) || 0;
    const futureDate = new Date(Date.now() + (inMin + totalMinutes) * 60000);
    expiryText = formatExpiryTime(futureDate);
  } else {
    const expiryDate = new Date(Date.now() + totalMinutes * 60000);
    expiryText = formatExpiryTime(expiryDate);
  }

  // Count unique domains from selected groups (or all if none selected)
  let domainCount = "—";
  let groupText = "—";
  try {
    const groupNames = selectedGroups.size > 0
      ? Array.from(selectedGroups)
      : Object.keys(availableGroups);
      
    if (selectedGroups.size === 0 && Object.keys(availableGroups).length > 0) {
      groupText = "All Groups";
    } else if (groupNames.length > 0) {
      groupText = groupNames.join(", ");
    }
    
    const uniqueDomains = new Set();
    for (const name of groupNames) {
      const domains = availableGroups[name];
      if (Array.isArray(domains)) {
        domains.forEach((d) => uniqueDomains.add(d));
      }
    }
    domainCount = uniqueDomains.size > 0 ? `${uniqueDomains.size} domains` : "—";
  } catch {
    domainCount = "—";
    groupText = "—";
  }

  return { blockType, sessionType: sessionLabel, durationText, expiryText, domainCount, groupText };
}

/** Format a Date as a human-readable expiry time. */
function formatExpiryTime(date) {
  let hrs = date.getHours();
  const mins = String(date.getMinutes()).padStart(2, "0");
  const ampm = hrs >= 12 ? "PM" : "AM";
  hrs = hrs % 12 || 12;
  return `${hrs}:${mins} ${ampm}`;
}

/** Populate Block Details modal with computed values. */
function renderBlockDetailsModal(details) {
  const setEl = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  setEl("wdDetailType", details.blockType);
  setEl("wdDetailSession", details.sessionType);
  setEl("wdDetailDuration", details.durationText);
  setEl("wdDetailExpiry", details.expiryText);
  setEl("wdDetailGroups", details.groupText);
  setEl("wdDetailDomains", details.domainCount);

  // Hide error state on fresh render
  const errorEl = document.getElementById("wdBlockDetailsError");
  if (errorEl) errorEl.classList.add("hidden");
}

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

      // Lazy-load tracking data when Tracking tab is activated
      if (targetId === "tab-tracking") {
        refreshTracking(trackingRange);
      }
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
        updateSetupSummaries();
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
      
      const btnScheduleAdd = document.getElementById("btnScheduleAdd");
      if (btnScheduleAdd) {
        btnScheduleAdd.textContent = "Add Schedule";
      }
      updateSetupSummaries();
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
      updateSetupSummaries();
    });
  });

  $$(".pomo-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".pomo-preset").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      els.pomoFocus.value = btn.dataset.focus;
      els.pomoBreak.value = btn.dataset.break;
      updatePomoSummary();
      updateSetupSummaries();
    });
  });

  [els.pomoFocus, els.pomoBreak, els.pomoCycles].forEach((el) => {
    el.addEventListener("input", () => {
      $$(".pomo-preset").forEach((b) => b.classList.remove("active"));
      updatePomoSummary();
      updateSetupSummaries();
    });
  });

  // Duration buttons (exclude pomo-preset buttons which share .dur-btn class)
  $$(".dur-btn:not(.pomo-preset)").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".dur-btn:not(.pomo-preset)").forEach((b) =>
        b.classList.remove("active"),
      );
      btn.classList.add("active");
      selectedDuration = parseInt(btn.dataset.minutes, 10);
      els.customMinutes.value = "";
      updateSetupSummaries();
    });
  });

  els.customMinutes.addEventListener("input", () => {
    const val = parseInt(els.customMinutes.value, 10);
    if (val > 0) {
      $$(".dur-btn").forEach((b) => b.classList.remove("active"));
      selectedDuration = val;
      updateSetupSummaries();
    }
  });

  if (els.scheduleIn) {
    els.scheduleIn.addEventListener("input", updateSetupSummaries);
  }
  // For scheduleAt, it might be updated by flatpickr.
  // We can hook into its change event or flatpickr's onChange.
  if (els.scheduleAt) {
    els.scheduleAt.addEventListener("change", updateSetupSummaries);
    els.scheduleAt.addEventListener("input", updateSetupSummaries);
  }

  if (els.btnSaveTemplate) {
    els.btnSaveTemplate.addEventListener("click", () => {
      els.templateNameInput.value = "";
      els.templateIntentInput.value = "";
      els.templateModal.classList.remove("hidden");
      els.templateNameInput.focus();
    });
  }

  if (els.btnCancelTemplate) {
    els.btnCancelTemplate.addEventListener("click", () => {
      els.templateModal.classList.add("hidden");
    });
  }

  if (els.templateNameInput) {
    els.templateNameInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveTemplateFromCurrent();
      }
    });
  }

  if (els.btnConfirmTemplate) {
    els.btnConfirmTemplate.addEventListener("click", saveTemplateFromCurrent);
  }

  const btnScheduleAdd = document.getElementById("btnScheduleAdd");
  if (btnScheduleAdd) {
    btnScheduleAdd.addEventListener("click", () => {
      activeStartFlow = scheduleType;
      // Basic validation for schedules before showing modal
      if (activeStartFlow === "in") {
        const min = parseInt(els.scheduleIn.value);
        if (!min || min < 1) {
          showToast("Please enter a valid number of minutes.");
          return;
        }
      } else if (activeStartFlow === "at") {
        const time = els.scheduleAt.value;
        if (!time) {
          showToast("Please select a valid date and time.");
          return;
        }
      }

      const blockDetailsModal = $("#blockDetailsModal");
      if (blockDetailsModal) {
        const details = computeBlockDetails();
        renderBlockDetailsModal(details);
        blockDetailsModal.classList.remove("hidden");
      }
    });
  }

  // Start button -> Shows Block Details Modal first
  els.btnStart.addEventListener("click", () => {
    activeStartFlow = "now";
    // Basic validation before showing modal
    const blockDetailsModal = $("#blockDetailsModal");
    if (blockDetailsModal) {
      const details = computeBlockDetails();
      renderBlockDetailsModal(details);
      blockDetailsModal.classList.remove("hidden");
    }
  });

  // Block Details — Cancel
  const wdBtnCancelDetails = $("#wdBtnCancelDetails");
  if (wdBtnCancelDetails) {
    wdBtnCancelDetails.addEventListener("click", () => {
      $("#blockDetailsModal").classList.add("hidden");
    });
  }

  // Block Details — Confirm → proceed to Intent Modal
  const wdBtnConfirmDetails = $("#wdBtnConfirmDetails");
  if (wdBtnConfirmDetails) {
    wdBtnConfirmDetails.addEventListener("click", () => {
      $("#blockDetailsModal").classList.add("hidden");

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
  }

  // Block Details — Overlay click to close
  const blockDetailsModal = $("#blockDetailsModal");
  if (blockDetailsModal) {
    blockDetailsModal.addEventListener("click", (e) => {
      if (e.target === blockDetailsModal) {
        blockDetailsModal.classList.add("hidden");
      }
    });
  }

  // Block Details — Retry (re-fetch groups)
  const wdBtnRetry = $("#wdBlockDetailsRetry");
  if (wdBtnRetry) {
    wdBtnRetry.addEventListener("click", async () => {
      await refreshGroups();
      const details = computeBlockDetails();
      renderBlockDetailsModal(details);
    });
  }

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

      if (activeStartFlow === "in") {
        payload.schedule_in = parseInt(els.scheduleIn.value);
      } else if (activeStartFlow === "at") {
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
          const confirmed = await waitForStatusConfirmation((status) =>
            sessionStatusMatchesPayload(status, payload),
          );
          if (!confirmed) {
            showToast("Request accepted; waiting for daemon confirmation.");
          } else if (payload.schedule_in || payload.schedule_at) {
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
  if (els.recurringDays) {
    els.recurringDays.querySelectorAll('.day-btn').forEach(btn => {
      btn.addEventListener('click', (event) => {
        event.preventDefault();
        btn.classList.toggle('active');
        const day = parseInt(btn.dataset.day, 10);
        if (selectedRecurringDays.includes(day)) {
          selectedRecurringDays = selectedRecurringDays.filter(d => d !== day);
        } else {
          selectedRecurringDays.push(day);
        }
        updateSetupSummaries();
      });
    });
  }

  if (els.recurringName) {
    els.recurringName.addEventListener("input", updateSetupSummaries);
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

      const payload = buildRecurringPayloadFromCurrent();

      const originalBtnHTML = els.btnAddRecurring.innerHTML;
      els.btnAddRecurring.innerHTML = '<span class="btn-spinner"></span> Adding...';
      els.btnAddRecurring.disabled = true;

      try {
        const res = await api("POST", "/api/schedules/recurring", payload);
        if (res.status === "ok") {
          showToast("Recurring schedule added successfully.");
          if (res.rule) {
            syncRecurringCache(res.rule);
          }
          await refreshStatus();
          selectedRecurringDays = [];
          els.recurringDays.querySelectorAll('.day-btn').forEach(b => b.classList.remove('active'));
          if (els.recurringName) els.recurringName.value = "";
          els.recurringTime.value = "";
          delete els.recurringTime.dataset.value;
          updateSetupSummaries();
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

  if (els.recurringEditDays) {
    els.recurringEditDays.querySelectorAll(".day-btn").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        const day = parseInt(btn.dataset.day, 10);
        if (editRecurringDays.includes(day)) {
          editRecurringDays = editRecurringDays.filter((item) => item !== day);
        } else {
          editRecurringDays.push(day);
        }
        setRecurringDayButtons(els.recurringEditDays, editRecurringDays);
      });
    });
  }

  if (els.recurringEditTime) {
    els.recurringEditTime.addEventListener("click", () => openPicker(els.recurringEditTime, 'time'));
  }

  if (els.recurringEditType) {
    els.recurringEditType.addEventListener("change", updateEditModalFields);
  }

  if (els.btnCancelRecurringEdit) {
    els.btnCancelRecurringEdit.addEventListener("click", closeRecurringEditModal);
  }

  if (els.btnSaveRecurringEdit) {
    els.btnSaveRecurringEdit.addEventListener("click", saveRecurringEdit);
  }

  if (els.recurringEditModal) {
    els.recurringEditModal.addEventListener("click", (event) => {
      if (event.target === els.recurringEditModal) closeRecurringEditModal();
    });
  }

  // Rescue button
  els.btnRescue.addEventListener("click", async () => {
    if (isSessionActive) {
      showToast("Rescue can start after the current focus session is unlocked or finished.");
      return;
    }
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
        const confirmed = await waitForStatusConfirmation((status) =>
          sessionStatusMatchesPayload(status, payload),
        );
        if (confirmed) {
          showToast(res.message);
        } else {
          showToast("Rescue request accepted; waiting for daemon confirmation.");
        }
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

  // Continue Focus (cancel pending unlock)
  const btnContinueFocus = $("#btnContinueFocus");
  if (btnContinueFocus) {
    btnContinueFocus.addEventListener("click", async () => {
      btnContinueFocus.disabled = true;
      try {
        const res = await api("POST", "/api/cancel-stop");
        if (res.status === "ok") {
          showToast(res.message);
          refreshStatus();
          updateSetupSummaries();
        } else {
          showToast("Error: " + res.message);
        }
      } catch (err) {
        showToast("Connection failed.");
      } finally {
        btnContinueFocus.disabled = false;
      }
    });
  }

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
        const confirmed = await waitForStatusConfirmation(stopStatusConfirmed);
        if (confirmed) {
          els.stopModal.classList.add("hidden");
          showToast(res.message);
          updateSetupSummaries();
        } else {
          showToast("Unlock accepted; waiting for daemon confirmation.");
        }
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
    updateSetupSummaries();
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
      if (els.recurringEditModal && !els.recurringEditModal.classList.contains("hidden")) {
        closeRecurringEditModal();
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



function updateLiveCountdowns() {
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
}

// ── Tracking & Analytics ─────────────────────────────────────────────────────

async function refreshTracking(range) {
  trackingRange = range || trackingRange;
  const data = await api("GET", `/api/history?range=${encodeURIComponent(trackingRange)}`);
  if (data.status !== "ok") return;
  trackingData = data;
  renderTrackingSummary(data.summary);
  renderTrackingStreak(data.summary);
  renderTrackingChart(data.summary);
  renderTrackingHeatmap(data.summary);
  renderTrackingBreakdown(data.summary);
  renderTrackingRecent(data.entries);
}

function formatFocusTime(minutes) {
  if (!minutes || minutes <= 0) return "0m";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m}m`;
}

function renderTrackingSummary(summary) {
  const netFocusEl = document.getElementById("kpiValueNetFocusTime");
  const totalFocusEl = document.getElementById("kpiValueTotalFocusTime");
  const sessionsEl = document.getElementById("kpiValueSessions");
  const percentageEl = document.getElementById("kpiValuePercentageFocus");

  const netMinutes = summary.net_focus_minutes != null ? summary.net_focus_minutes : summary.total_focus_minutes;

  if (netFocusEl) netFocusEl.textContent = formatFocusTime(netMinutes);
  if (totalFocusEl) totalFocusEl.textContent = formatFocusTime(summary.total_focus_minutes);
  if (sessionsEl) sessionsEl.textContent = summary.total_sessions;

  if (percentageEl) {
    if (summary.daily_focus_goal_hours && summary.daily_focus_goal_hours > 0) {
      let days = 1;
      if (trackingRange === "week") days = 7;
      else if (trackingRange === "month") days = 30;
      else if (trackingRange === "year") days = 365;
      else if (trackingRange === "all") days = Math.max(1, Object.keys(summary.daily_totals || {}).length);

      const targetMinutes = summary.daily_focus_goal_hours * 60 * days;
      const percentage = Math.min(100, Math.round((netMinutes / targetMinutes) * 100));
      percentageEl.textContent = `${percentage}%`;
      percentageEl.parentElement.style.display = "block";
    } else {
      percentageEl.parentElement.style.display = "none";
    }
  }
}

function renderTrackingStreak(summary) {
  const currentEl = document.getElementById("streakCurrent");
  const longestEl = document.getElementById("streakLongest");
  const longestSessionEl = document.getElementById("streakLongestSession");
  if (currentEl) currentEl.textContent = summary.current_streak_days;
  if (longestEl) longestEl.textContent = summary.longest_streak_days;
  if (longestSessionEl) longestSessionEl.textContent = formatFocusTime(summary.longest_session_minutes);
}

function renderTrackingChart(summary) {
  const container = document.getElementById("trackingBarChart");
  const cardTitle = container.parentElement.querySelector(".card-title");
  if (!container) return;
  container.innerHTML = "";

  if (!trackingData || !trackingData.entries || trackingData.entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "tracking-empty-state";
    empty.textContent = "No session data for this period.";
    container.appendChild(empty);
    return;
  }

  let colCount, labels, getBucketKey, getBucketLabel;

  if (trackingRange === "today" || trackingRange === "yesterday") {
    if (cardTitle) cardTitle.textContent = "Hourly Focus";
    colCount = 24;
    labels = Array.from({length: 24}, (_, i) => i % 3 === 0 ? `${i}` : ""); // Show some labels
    getBucketKey = (e) => e.hour_started;
    getBucketLabel = (key) => `${key}:00`;
  } else if (trackingRange === "week") {
    if (cardTitle) cardTitle.textContent = "Daily Focus";
    colCount = 7;
    // day_of_week: 0 is Mon, 6 is Sun
    const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    labels = dayNames;
    getBucketKey = (e) => e.day_of_week;
    getBucketLabel = (key) => dayNames[key];
  } else if (trackingRange === "month") {
    if (cardTitle) cardTitle.textContent = "Daily Focus";
    colCount = 31;
    labels = Array.from({length: 31}, (_, i) => (i + 1) % 5 === 0 || i === 0 ? `${i + 1}` : "");
    getBucketKey = (e) => new Date(e.started_at).getDate() - 1; // 0-30 index
    getBucketLabel = (key) => `Day ${key + 1}`;
  } else {
    // year or all
    if (cardTitle) cardTitle.textContent = "Monthly Focus";
    colCount = 12;
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    labels = months;
    getBucketKey = (e) => new Date(e.started_at).getMonth(); // 0-11 index
    getBucketLabel = (key) => months[key];
  }

  // Initialize buckets
  const buckets = Array.from({length: colCount}, () => ({ minutes: 0, sessions: 0 }));

  // Aggregate
  trackingData.entries.forEach(e => {
    const key = getBucketKey(e);
    if (key >= 0 && key < colCount) {
      if (e.net_focus_minutes > 0) {
        buckets[key].minutes += e.net_focus_minutes;
        buckets[key].sessions += 1;
      }
    }
  });

  const maxMinutes = Math.max(...buckets.map(b => b.minutes), 1);
  const todayObj = new Date();
  
  // Highlight the current bucket depending on the range
  let currentKey = -1;
  if (trackingRange === "today") currentKey = todayObj.getHours();
  else if (trackingRange === "week") {
    // JS getDay() is 0=Sun. We want 0=Mon
    currentKey = (todayObj.getDay() + 6) % 7;
  } else if (trackingRange === "month") {
    currentKey = todayObj.getDate() - 1;
  } else if (trackingRange === "year") {
    currentKey = todayObj.getMonth();
  }

  buckets.forEach((bucket, i) => {
    const heightPct = maxMinutes > 0 ? Math.max(2, (bucket.minutes / maxMinutes) * 100) : 2;

    const wrapper = document.createElement("div");
    wrapper.className = "tracking-bar-wrapper";

    const bar = document.createElement("div");
    bar.className = "tracking-bar";
    bar.style.height = `${heightPct}%`;
    bar.style.animation = `barGrow 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) ${i * 0.03}s both`;
    if (bucket.minutes === 0) {
      bar.style.background = "rgba(255,255,255,0.05)";
      bar.style.opacity = "0.4";
    }

    const tooltip = document.createElement("div");
    tooltip.className = "tracking-bar-tooltip";
    tooltip.textContent = `${getBucketLabel(i)}: ${formatFocusTime(bucket.minutes)} · ${bucket.sessions} session${bucket.sessions !== 1 ? "s" : ""}`;
    bar.appendChild(tooltip);

    const label = document.createElement("div");
    label.className = `tracking-bar-label${i === currentKey ? " today-label" : ""}`;
    label.textContent = labels[i];

    wrapper.appendChild(bar);
    wrapper.appendChild(label);
    container.appendChild(wrapper);
  });
}

function renderTrackingHeatmap(summary) {
  const grid = document.getElementById("trackingHeatmap");
  const hourLabelsEl = document.getElementById("heatmapHourLabels");
  if (!grid || !hourLabelsEl) return;
  grid.innerHTML = "";
  hourLabelsEl.innerHTML = "";

  // Set up configuration based on trackingRange
  let colCount, rowLabels, colLabels;
  let getCellKey; // function(rowIdx, colIdx) returns key in heatData
  let getCellTitle; // function(rowIdx, colIdx) returns tooltip text
  
  if (trackingRange === "today" || trackingRange === "yesterday") {
    colCount = 24;
    rowLabels = [trackingRange === "today" ? "Today" : "Yesterday"];
    colLabels = Array.from({length: 24}, (_, i) => i % 3 === 0 ? `${i}` : "");
    getCellKey = (r, c) => `${c}`; // Group by hour
    getCellTitle = (r, c) => `${c}:00`;
  } else if (trackingRange === "month") {
    // 31 columns, 1 row
    colCount = 31;
    rowLabels = ["This Month"];
    colLabels = Array.from({length: 31}, (_, i) => (i + 1) % 5 === 0 || i === 0 ? `${i + 1}` : "");
    getCellKey = (r, c) => `${c + 1}`; // Group by day of month
    getCellTitle = (r, c) => `Day ${c + 1}`;
  } else if (trackingRange === "year" || trackingRange === "all") {
    // 12 columns, 1 row
    colCount = 12;
    rowLabels = [trackingRange === "year" ? "This Year" : "All Time"];
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    colLabels = months;
    getCellKey = (r, c) => `${c}`; // Group by month
    getCellTitle = (r, c) => `${months[c]}`;
  } else {
    // Week (default)
    colCount = 24;
    rowLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    colLabels = Array.from({length: 24}, (_, i) => i % 3 === 0 ? `${i}` : "");
    getCellKey = (r, c) => `${r}:${c}`; // dow:hour
    getCellTitle = (r, c) => `${rowLabels[r]} ${c}:00`;
  }

  // Build per-cell data from entries
  const heatData = {}; 
  if (trackingData && trackingData.entries) {
    trackingData.entries.forEach(e => {
      let key;
      if (e.net_focus_minutes <= 0) return; // Only count true focus sessions in heatmap
      
      const d = new Date(e.started_at);
      if (trackingRange === "today" || trackingRange === "yesterday") {
        key = `${e.hour_started}`;
      } else if (trackingRange === "month") {
        key = `${d.getDate()}`;
      } else if (trackingRange === "year" || trackingRange === "all") {
        key = `${d.getMonth()}`;
      } else {
        key = `${e.day_of_week}:${e.hour_started}`;
      }
      heatData[key] = (heatData[key] || 0) + 1; // Count of focus blocks
    });
  }
  const maxCount = Math.max(...Object.values(heatData), 1);

  // Apply grid template styles inline to allow dynamic column counts
  const gridTemplate = `50px repeat(${colCount}, 1fr)`;
  hourLabelsEl.style.gridTemplateColumns = gridTemplate;

  // Hour/Column labels row
  const cornerLabel = document.createElement("div");
  cornerLabel.className = "heatmap-hour-label";
  hourLabelsEl.appendChild(cornerLabel);
  for (let c = 0; c < colCount; c++) {
    const lbl = document.createElement("div");
    lbl.className = "heatmap-hour-label";
    lbl.textContent = colLabels[c];
    hourLabelsEl.appendChild(lbl);
  }

  // Data rows
  rowLabels.forEach((rowName, r) => {
    const row = document.createElement("div");
    row.className = "heatmap-row";
    row.style.gridTemplateColumns = gridTemplate;

    const rowLbl = document.createElement("div");
    rowLbl.className = "heatmap-day-label";
    rowLbl.textContent = rowName;
    row.appendChild(rowLbl);

    for (let c = 0; c < colCount; c++) {
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";
      const key = getCellKey(r, c);
      const count = heatData[key] || 0;
      if (count > 0) {
        const intensity = Math.min(5, Math.ceil((count / maxCount) * 5));
        cell.dataset.intensity = intensity;
        cell.title = `${getCellTitle(r, c)} — ${count} session${count !== 1 ? "s" : ""}`;
      } else {
        cell.title = `${getCellTitle(r, c)} — 0 sessions`;
      }
      row.appendChild(cell);
    }
    grid.appendChild(row);
  });
}

function renderTrackingBreakdown(summary) {
  const modeContainer = document.getElementById("modeBreakdown");
  const modeLegend = document.getElementById("modeLegend");
  const typeContainer = document.getElementById("typeBreakdown");
  const typeLegend = document.getElementById("typeLegend");

  const modeColors = { lock: "#6366f1", break: "#10b981" };
  const modeLabels = { lock: "Lock", break: "Break" };
  const typeColors = { standard: "#6366f1", pomodoro: "#f59e0b", rescue: "#a855f7" };
  const typeLabels = { standard: "Standard", pomodoro: "Pomodoro", rescue: "Rescue" };

  function renderBar(container, legendEl, data, colors, labels, formatFn = (x) => x) {
    if (!container || !legendEl) return;
    container.innerHTML = "";
    legendEl.innerHTML = "";
    const total = Object.values(data).reduce((a, b) => a + b, 0);
    if (total === 0) {
      const empty = document.createElement("div");
      empty.className = "breakdown-empty";
      empty.textContent = "No data";
      container.appendChild(empty);
      return;
    }
    Object.entries(data).forEach(([key, count]) => {
      if (count <= 0) return;
      const pct = (count / total) * 100;
      const seg = document.createElement("div");
      seg.className = "breakdown-segment";
      seg.style.width = `${pct}%`;
      seg.style.background = colors[key] || "#6366f1";
      seg.title = `${labels[key] || key}: ${formatFn(count)} (${Math.round(pct)}%)`;
      container.appendChild(seg);

      const legendItem = document.createElement("div");
      legendItem.className = "breakdown-legend-item";
      const dot = document.createElement("div");
      dot.className = "breakdown-legend-dot";
      dot.style.background = colors[key] || "#6366f1";
      legendItem.appendChild(dot);
      const text = document.createTextNode(`${labels[key] || key} (${formatFn(count)})`);
      legendItem.appendChild(text);
      legendEl.appendChild(legendItem);
    });
  }

  const netMinutes = summary.net_focus_minutes != null ? summary.net_focus_minutes : summary.total_focus_minutes;
  const breakMinutes = Math.max(0, summary.total_focus_minutes - netMinutes);
  const modeData = { lock: netMinutes, break: breakMinutes };

  renderBar(modeContainer, modeLegend, modeData, modeColors, modeLabels, formatFocusTime);
  renderBar(typeContainer, typeLegend, summary.by_type || {}, typeColors, typeLabels);
}

function renderTrackingRecent(entries) {
  const list = document.getElementById("trackingRecentList");
  const countEl = document.getElementById("recentSessionsCount");
  if (!list) return;
  list.innerHTML = "";
  if (countEl) countEl.textContent = entries.length;

  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "tracking-empty-state";
    empty.textContent = "No sessions recorded yet.";
    list.appendChild(empty);
    return;
  }

  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // Show newest first, limit to 50
  const sorted = entries.slice().reverse().slice(0, 50);
  sorted.forEach(entry => {
    const item = document.createElement("div");
    item.className = "recent-session-item";

    // Date column
    const dateCol = document.createElement("div");
    dateCol.className = "recent-session-date";
    try {
      const d = new Date(entry.started_at);
      const monthSpan = document.createElement("div");
      monthSpan.className = "recent-session-month";
      monthSpan.textContent = monthNames[d.getMonth()];
      const daySpan = document.createElement("div");
      daySpan.className = "recent-session-day";
      daySpan.textContent = d.getDate();
      dateCol.appendChild(monthSpan);
      dateCol.appendChild(daySpan);
    } catch (e) {
      dateCol.textContent = "--";
    }

    // Details column
    const details = document.createElement("div");
    details.className = "recent-session-details";

    const timeRow = document.createElement("div");
    timeRow.className = "recent-session-time";
    try {
      const d = new Date(entry.started_at);
      const h = d.getHours();
      const m = String(d.getMinutes()).padStart(2, "0");
      const period = h >= 12 ? "PM" : "AM";
      const h12 = h % 12 || 12;
      timeRow.textContent = `${h12}:${m} ${period} · ${formatFocusTime(entry.duration_minutes)}`;
    } catch (e) {
      timeRow.textContent = `${formatFocusTime(entry.duration_minutes)}`;
    }

    const meta = document.createElement("div");
    meta.className = "recent-session-meta";

    // Mode chip
    const modeChip = document.createElement("span");
    modeChip.className = `recent-session-chip chip-mode-${entry.mode || "blacklist"}`;
    modeChip.textContent = (entry.mode || "blacklist") === "whitelist" ? "Whitelist" : "Blacklist";
    meta.appendChild(modeChip);

    // Type and Phase chips
    const st = entry.session_type || "standard";
    if (st === "pomodoro") {
      const typeChip = document.createElement("span");
      typeChip.className = "recent-session-chip chip-type-pomodoro";
      typeChip.textContent = "Pomodoro";
      meta.appendChild(typeChip);

      const phase = entry.pomo_phase || "focus";
      const phaseChip = document.createElement("span");
      phaseChip.className = `recent-session-chip chip-phase-${phase}`;
      phaseChip.style.background = phase === "focus" ? "rgba(99, 102, 241, 0.15)" : "rgba(16, 185, 129, 0.15)";
      phaseChip.style.color = phase === "focus" ? "#818cf8" : "#34d399";
      phaseChip.textContent = phase === "focus" ? "🔒 Lock" : "☕ Break";
      meta.appendChild(phaseChip);
    } else if (st === "rescue") {
      const typeChip = document.createElement("span");
      typeChip.className = "recent-session-chip chip-type-rescue";
      typeChip.textContent = "Rescue";
      meta.appendChild(typeChip);
    }

    // Duration chip
    const durChip = document.createElement("span");
    durChip.className = "recent-session-chip";
    durChip.textContent = formatFocusTime(entry.duration_minutes);
    meta.appendChild(durChip);

    details.appendChild(timeRow);
    details.appendChild(meta);

    // Intent
    if (entry.intent) {
      const intentEl = document.createElement("div");
      intentEl.className = "recent-session-intent";
      intentEl.textContent = `🎯 ${entry.intent}`;
      intentEl.dir = "auto";
      details.appendChild(intentEl);
    }

    // Status icon
    const status = document.createElement("div");
    status.className = `recent-session-status ${entry.completed_normally ? "completed" : "unlocked"}`;
    status.textContent = entry.completed_normally ? "✓" : "🔓";
    status.title = entry.completed_normally ? "Completed normally" : "Ended via unlock";

    item.appendChild(dateCol);
    item.appendChild(details);
    item.appendChild(status);
    list.appendChild(item);
  });
}

function initTrackingEvents() {
  document.querySelectorAll(".tracking-range-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tracking-range-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      refreshTracking(btn.dataset.range);
    });
  });
}

async function init() {
  setInterval(updateLiveCountdowns, 1000);
  initEvents();
  initPickerEvents();
  initTrackingEvents();

  try {

    await refreshStatus();
    await refreshLists();
    await refreshPermaBlocklist();
    await refreshGroups();
    await refreshTemplates();
    await loadSettings();
  } catch (err) {
    console.error("[ForcedFocus] Init failed:", err);
  } finally {
    const loader = document.getElementById("appLoader");
    if (loader) {
      loader.classList.add("fade-out");
      setTimeout(() => loader.remove(), 500);
    }
  }

  // S10: Set min datetime to now, preventing past date selection
  if (els.scheduleAt) {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const minVal = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    els.scheduleAt.min = minVal;
  }

  // Modernized IPC: Server-Sent Events (SSE) instead of aggressive polling
  let eventSource = null;
  let sseReconnectTimer = null;

  function scheduleSSEReconnect() {
    if (sseReconnectTimer) return;
    sseReconnectTimer = setTimeout(() => {
      sseReconnectTimer = null;
      connectSSE();
    }, 3000);
  }

  function connectSSE() {
    if (eventSource && (eventSource.readyState === 0 || eventSource.readyState === 1)) return;
    if (sseReconnectTimer) {
      clearTimeout(sseReconnectTimer);
      sseReconnectTimer = null;
    }
    if (eventSource) eventSource.close();
    eventSource = new EventSource(API + "/api/stream");
    
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        // SSE delivers full status payloads — apply directly
        const phaseChanged = data.pomo_phase !== _lastPomoPhase;
        const activeChanged = data.active !== _lastActiveState;
        // Keep SSE active to drive the native menubar countdown via nativeCallback
        if (phaseChanged || activeChanged) {
          cancelCountdownFrame();
          countdownSignature = "";
        }
        _lastPomoPhase = data.pomo_phase || null;
        _lastActiveState = data.active;
        setActiveUI(data);
        
        // Instant Config Sync
        if (typeof _lastRevision === "undefined") {
          _lastRevision = data.state_revision;
        } else if (data.state_revision !== undefined && data.state_revision > _lastRevision) {
          _lastRevision = data.state_revision;
          // Silently refresh configurations when another window modifies them
          refreshLists();
          refreshGroups();
          refreshTemplates();
          loadSettings();
          refreshPermaBlocklist();
          refreshTracking(trackingRange);
        }
      } catch (err) {
        console.error("SSE parse error:", err);
      }
    };
    
    eventSource.onerror = () => {
      console.warn("SSE connection lost. Reconnecting in 3s...");
      eventSource.close();
      eventSource = null;
      scheduleSSEReconnect();
    };
  }

  connectSSE();

  // P4: Pause SSE when tab is hidden to save resources
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (sseReconnectTimer) {
        clearTimeout(sseReconnectTimer);
        sseReconnectTimer = null;
      }
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
    // WB3: Safe DOM construction — no innerHTML with markup strings
    els.sessionGroups.replaceChildren();
    const emptyMsg = document.createElement("div");
    emptyMsg.className = "loading-muted";
    emptyMsg.textContent = "No groups configured in Settings.";
    els.sessionGroups.appendChild(emptyMsg);
    return;
  }

  els.sessionGroups.innerHTML = "";
  for (const name of Object.keys(availableGroups)) {
    const btn = document.createElement("button");
    btn.className = "dur-btn group-chip" + (selectedGroups.has(name) ? " active" : "");
    btn.dataset.group = name;
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
      updateRecurringSetupSummary();
    });
    els.sessionGroups.appendChild(btn);
  }
  updateRecurringSetupSummary();
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

function convertToDisplayTime(time24) {
  if (!time24) return "";
  const parts = time24.split(":");
  if (parts.length < 2) return time24;
  const hrs = parseInt(parts[0], 10);
  const mins = parseInt(parts[1], 10);
  return formatTimeDisplay(hrs, mins);
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
    if (pickerState.targetInput === els.recurringTime || pickerState.targetInput === els.scheduleAt) {
      updateSetupSummaries();
    }
  }
  
  if (pickerState.targetInput === els.scheduleAt) {
      updateSetupSummaries();
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
