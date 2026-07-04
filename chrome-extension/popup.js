/**
 * ForcedFocus Chrome Extension — Popup Logic
 * Controls session start/stop, displays timer, and manages UI state.
 */

import { formatTime } from "./shared/utils.js";
import { renderIntentTasks } from "./shared/intent-tasks.js";

const API = "http://127.0.0.1:7070";
let mode = "blacklist";
let duration = 120;
let animationFrameId = null;
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
  if (window.apiToken) {
    apiToken = window.apiToken;
    return;
  }
  try {
    const res = await fetch(API + "/", {
      signal: AbortSignal.timeout(2000),
    });
    const html = await res.text();
    const match = html.match(/window\.apiToken\s*=\s*["']([^"']+)["']/);
    if (match && match[1]) {
      apiToken = match[1];
    }
  } catch (e) {
    console.error("[ForcedFocus] Token load failed:", e);
  }
}

async function api(method, path, body = null) {
  const headers = { "Content-Type": "application/json" };
  if (apiToken) {
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
    if (res.status === 401) {
      await loadApiToken();
      if (apiToken) headers["X-API-Token"] = apiToken;
      const retry = await fetch(API + path, {
        method,
        headers,
        body: opts.body,
        signal: AbortSignal.timeout(5000), // B3: Prevent indefinite hang on retry
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

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sessionStatusMatchesPayload(status, payload) {
  if (!status || status.status !== "ok") return false;
  return (
    status.active === true &&
    status.mode === payload.mode &&
    status.session_type === (payload.session_type || "standard")
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
      renderStatus(status);
      return status;
    }
    if (attempt < attempts - 1) await delay(delayMs);
  }
  return null;
}

// ── Timer (P1: wall-clock anchor + R4: no negative values) ──────────────────



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
  if (animationFrameId && Math.abs(currentRemaining - secs) <= 2) return;
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }

  const anchor = Date.now();
  const durationMs = secs * 1000;
  const endTime = anchor + durationMs;
  currentRemaining = secs;

  const timerValue = $("#timerValue");
  const timerLabel = $("#timerLabel");

  if (timerValue) timerValue.textContent = formatTime(currentRemaining);
  if (timerLabel) timerLabel.textContent = "REMAINING";
  updateRing(currentRemaining);

  let lastSecs = -1;

  const tick = () => {
    const now = Date.now();
    const remMs = endTime - now;

    if (remMs <= 0) {
      animationFrameId = null;
      if (timerValue) timerValue.textContent = formatTime(0);
      updateRing(0);
      refresh();
      return;
    }

    const remSecs = Math.ceil(remMs / 1000);
    currentRemaining = remSecs;

    if (remSecs !== lastSecs) {
      if (timerValue) timerValue.textContent = formatTime(currentRemaining);
      lastSecs = remSecs;
    }
    
    updateRing(remMs / 1000);
    animationFrameId = requestAnimationFrame(tick);
  };

  animationFrameId = requestAnimationFrame(tick);
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
  if (names.length === 0 || mode === "ban") {
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
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
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
          renderIntentTasks(intentTasksContainer, data.intent_tasks || [], api, data.intent);
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



async function refresh(stateData) {
  try {
    if (stateData) {
      renderStatus(stateData);
    } else {
      const data = await api("GET", "/api/status");
      if (data.status === "ok") {
        renderStatus(data);
      }
    }
  } catch (error) {
    console.error("Failed to refresh status:", error);
  }
}

// ── Block Details ────────────────────────────────────────────────────────────

/**
 * Compute session configuration preview from current local state.
 * All data is client-side — no API call needed.
 * @returns {{ blockType: string, sessionType: string, durationText: string, expiryText: string, domainCount: string }}
 */
function computeBlockDetails() {
  const blockType = mode === "whitelist" ? "✅ Whitelist" : mode === "ban" ? "⛔ Ban" : "🚫 Blacklist";
  const sessionLabel = sessionType === "pomodoro" ? "🍅 Pomodoro" : "⏱ Standard";

  let totalMinutes;
  let durationText;
  if (sessionType === "pomodoro") {
    totalMinutes = (pomoFocusMin + pomoBreakMin) * pomoCycles;
    durationText = `${pomoFocusMin}m focus × ${pomoCycles} cycles`;
  } else {
    totalMinutes = duration;
    const hrs = Math.floor(duration / 60);
    const mins = duration % 60;
    durationText = hrs > 0 ? `${hrs}h ${mins > 0 ? mins + "m" : ""}`.trim() : `${mins}m`;
  }

  // Compute expiry from now + totalMinutes
  const expiryDate = new Date(Date.now() + totalMinutes * 60000);
  let expiryHrs = expiryDate.getHours();
  const expiryMins = String(expiryDate.getMinutes()).padStart(2, "0");
  const ampm = expiryHrs >= 12 ? "PM" : "AM";
  expiryHrs = expiryHrs % 12 || 12;
  const expiryText = `${expiryHrs}:${expiryMins} ${ampm}`;

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

/** Populate Block Details dialog with computed values. */
function renderBlockDetails(details) {
  const setEl = (id, text) => {
    const el = $("#" + id);
    if (el) el.textContent = text;
  };
  setEl("detailType", details.blockType);
  setEl("detailSession", details.sessionType);
  setEl("detailDuration", details.durationText);
  setEl("detailExpiry", details.expiryText);
  setEl("detailGroups", details.groupText);
  setEl("detailDomains", details.domainCount);

  // Hide error state on fresh render
  const errorEl = $("#blockDetailsError");
  if (errorEl) errorEl.classList.add("hidden");
}

/** Show error message in Block Details dialog. */
function showBlockDetailsError(msg) {
  const errorEl = $("#blockDetailsError");
  const msgEl = $("#blockDetailsErrorMsg");
  if (errorEl && msgEl) {
    msgEl.textContent = msg;
    errorEl.classList.remove("hidden");
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
      renderGroups();
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

  // Start — Shows Block Details Dialog first, then Intent Dialog on confirm
  const btnStart = $("#btnStart");
  if (btnStart) {
    btnStart.addEventListener("click", () => {
      const blockDetailsDialog = $("#blockDetailsDialog");
      if (blockDetailsDialog) {
        const details = computeBlockDetails();
        renderBlockDetails(details);
        blockDetailsDialog.classList.remove("hidden");
      }
    });
  }

  // Block Details — Cancel
  const btnCancelDetails = $("#btnCancelDetails");
  if (btnCancelDetails) {
    btnCancelDetails.addEventListener("click", () => {
      const blockDetailsDialog = $("#blockDetailsDialog");
      if (blockDetailsDialog) blockDetailsDialog.classList.add("hidden");
    });
  }

  // Block Details — Confirm → proceed to Intent Dialog
  const btnConfirmDetails = $("#btnConfirmDetails");
  if (btnConfirmDetails) {
    btnConfirmDetails.addEventListener("click", () => {
      const blockDetailsDialog = $("#blockDetailsDialog");
      if (blockDetailsDialog) blockDetailsDialog.classList.add("hidden");

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

  // Block Details — Retry (re-fetch groups data)
  const btnRetryDetails = $("#blockDetailsRetry");
  if (btnRetryDetails) {
    btnRetryDetails.addEventListener("click", async () => {
      await fetchGroups();
      const details = computeBlockDetails();
      renderBlockDetails(details);
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

      const originalBtnHTML = btnStart.innerHTML;
      btnStart.innerHTML = '<span class="btn-spinner"></span> Starting...';
      btnStart.disabled = true;
      btnStart.setAttribute("aria-busy", "true");

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
          const confirmed = await waitForStatusConfirmation((status) =>
            sessionStatusMatchesPayload(status, payload),
          );
          if (!confirmed) {
            showError("Session request accepted; waiting for daemon confirmation.");
          }
        } else {
          showError(res.message || "Failed to start session.");
        }
      } catch (error) {
        showError(`Failed to start session: ${error.message}`);
      } finally {
        btnStart.innerHTML = originalBtnHTML;
        btnStart.disabled = false;
        btnStart.removeAttribute("aria-busy");
      }
    });
  }

  // Rescue — R6: disable button during async
  const btnRescue = $("#btnRescue");
  if (btnRescue) {
    btnRescue.addEventListener("click", async () => {
      const originalRescueHTML = btnRescue.innerHTML;
      btnRescue.innerHTML = '<span class="btn-spinner"></span> Activating...';
      btnRescue.disabled = true;
      btnRescue.setAttribute("aria-busy", "true");

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
          const confirmed = await waitForStatusConfirmation((status) =>
            sessionStatusMatchesPayload(status, payload),
          );
          if (!confirmed) {
            showError("Rescue request accepted; waiting for daemon confirmation.");
          }
        } else {
          showError(res.message || "Failed to activate rescue.");
        }
      } catch (error) {
        showError(`Failed to activate rescue: ${error.message}`);
      } finally {
        btnRescue.innerHTML = originalRescueHTML;
        btnRescue.disabled = false;
        btnRescue.removeAttribute("aria-busy");
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
          const confirmed = await waitForStatusConfirmation(stopStatusConfirmed);
          if (confirmed) {
            const stopDialog = $("#stopDialog");
            if (stopDialog) stopDialog.classList.add("hidden");
          } else {
            showError("Unlock accepted; waiting for daemon confirmation.");
          }
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


  // Listen for state updates from the background worker's SSE connection
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === "stateUpdated" || msg.action === "phaseChanged") {
      refresh(msg.state); // If msg.state is provided, refresh can use it or just fetch
    }
  });

  // Fetch status FIRST, then render — eliminates 00:00 flash on popup open
  await refresh();
}

document.addEventListener("DOMContentLoaded", init);
