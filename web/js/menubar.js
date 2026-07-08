import { api as sharedApi } from "../shared/api.js";

const API = "http://127.0.0.1:7070";
let currentMode = "blacklist";
let currentType = "standard";
let totalSecs = 0;
let currentRemaining = 0;
let animationFrameId = null;
let apiToken = "";
let selectedGroups = [];
let availableGroups = {};
let availableLists = { blacklist: [], whitelist: [] };
let sessionTemplates = [];
let isPopoverVisible = false;
let unlockRemainingSeconds = 0;
let unlockEndTime = 0;
let unlockReleaseTime = "";
let _lastRevision = undefined;

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
    this._current = new Audio("/assets/sounds/" + encodeURIComponent(file));
    this._current.play().catch((e) => console.error("Audio error:", e));
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

  // Block Details State
  blockDetailsState: $("#blockDetailsState"),
  mbBtnCancelDetails: $("#mbBtnCancelDetails"),
  mbBtnConfirmDetails: $("#mbBtnConfirmDetails"),
  mbBlockDetailsRetry: $("#mbBlockDetailsRetry"),

  // Intent UI
  intentState: $("#intentState"),
  intentPromptInput: $("#intentPromptInput"),
  btnIntentCancel: $("#btnIntentCancel"),
  btnIntentConfirm: $("#btnIntentConfirm"),

  // Group UI
  groupSection: $("#groupSection"),
  groupGrid: $("#groupGrid"),
  groupCount: $("#groupCount"),
  notificationFallback: $("#mbNotificationFallback"),
  mbTemplatesList: $("#mbTemplatesList"),
  mbTemplatesCount: $("#mbTemplatesCount"),
};

const api = (method, path, body = null) => sharedApi(method, path, body, API);

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

function updateRing(remMs) {
  const circ = 565.48; // 2 * Math.PI * 90
  const totalMs = totalSecs * 1000;
  // Fill the ring clockwise as time passes
  const prog = totalMs > 0 ? 1 - remMs / totalMs : 0;

  els.progress.style.strokeDasharray = `${Math.max(0, Math.min(1, prog)) * circ} ${circ}`;
  els.progress.style.strokeDashoffset = 0;
}

function updateUnlockPendingDisplay() {
  const mbUnlockInfo = document.getElementById("mbUnlockInfo");
  if (!mbUnlockInfo || mbUnlockInfo.classList.contains("hidden")) return;
  
  const now = Date.now();
  const remMs = Math.max(0, unlockEndTime - now);
  const remSecs = Math.ceil(remMs / 1000);
  
  let timeStr = "";
  const m = Math.floor(remSecs / 60);
  const s = remSecs % 60;
  if (m > 0) {
    timeStr = `${m}m ${s}s`;
  } else {
    timeStr = `${s}s`;
  }
  
  const p = mbUnlockInfo.querySelector("p");
  if (p) {
    p.textContent = `⏱ Unlock pending — releases at ${unlockReleaseTime} (${timeStr} left)`;
  }
}

function showNotificationFallback(message) {
  if (!els.notificationFallback) return;
  if (!message) {
    els.notificationFallback.classList.add("hidden");
    els.notificationFallback.textContent = "";
    return;
  }
  els.notificationFallback.textContent = message;
  els.notificationFallback.classList.remove("hidden");
}

window.showNotificationFallback = showNotificationFallback;

function startCountdown(rem) {
  if (animationFrameId && Math.abs(currentRemaining - rem) <= 2) return;
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }

  currentRemaining = rem;
  const startTime = Date.now();
  const durationMs = rem * 1000;
  const endTime = startTime + durationMs;

  let lastSecs = -1;
  const tick = () => {
    const now = Date.now();
    const remMs = endTime - now;

    if (remMs <= 0) {
      animationFrameId = null;
      els.time.textContent = fmt(0);
      updateRing(0);
      refresh();
      return;
    }

    const remSecs = Math.ceil(remMs / 1000);
    currentRemaining = remSecs; // Update global state for drift guard comparison
    
    // Only update DOM text when second changes
    if (remSecs !== lastSecs) {
      els.time.textContent = fmt(remSecs);
      if (els.infoNextTime) els.infoNextTime.textContent = fmtClock(remSecs);
      lastSecs = remSecs;
    }

    updateRing(remMs);
    updateUnlockPendingDisplay();
    animationFrameId = requestAnimationFrame(tick);
  };

  animationFrameId = requestAnimationFrame(tick);
}

let isStarting = false;

function renderStatus(data) {
  if (isStarting) return; // Prevent UI jank while daemon applies kernel rules
  showNotificationFallback(data.notification_warning?.message || "");

  const mbUnlockInfo = document.getElementById("mbUnlockInfo");
  if (mbUnlockInfo) mbUnlockInfo.classList.add("hidden");

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
        data.session_type === "rescue" ? "RESCUE" : data.session_type === "prayer" ? "PRAYER" : data.mode.toUpperCase();
      els.infoType.textContent = data.session_type.toUpperCase();
      els.infoExpires.textContent = data.expires_at || "--:--";

      els.badgeText.textContent =
        data.session_type === "rescue" ? "RESCUE" : data.session_type === "prayer" ? "PRAYER" : "ACTIVE";
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
      
      // Handle pending unlock box
      if (data.pending_unlock) {
        els.btnStop.classList.add("hidden");
        const unlockDialog = document.getElementById("unlockDialog");
        if (unlockDialog) unlockDialog.classList.add("hidden");
        if (mbUnlockInfo) {
          mbUnlockInfo.classList.remove("hidden");
          unlockReleaseTime = data.pending_unlock;
          unlockRemainingSeconds = data.pending_unlock_seconds || 0;
          unlockEndTime = Date.now() + unlockRemainingSeconds * 1000;
          updateUnlockPendingDisplay();
        }
      } else {
        els.btnStop.classList.remove("hidden");
        
        // Enforce 30-minute buffer constraint for stopping session
        if (data.next_prayer_seconds !== undefined && data.next_prayer_seconds !== null && data.next_prayer_seconds <= 1800) {
          els.btnStop.disabled = true;
          els.btnStop.title = "Cannot stop session within 30 minutes of prayer time";
          // Also visually dim it
          els.btnStop.classList.add("opacity-50", "cursor-not-allowed");
        } else {
          els.btnStop.disabled = false;
          els.btnStop.title = "";
          els.btnStop.classList.remove("opacity-50", "cursor-not-allowed");
        }
        
        if (mbUnlockInfo) mbUnlockInfo.classList.add("hidden");
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
    const isBlockDetailsVisible = els.blockDetailsState && !els.blockDetailsState.classList.contains("hidden");
    if (!isIntentVisible && !isBlockDetailsVisible) {
      els.idleState.classList.remove("hidden");
      els.activeState.classList.add("hidden");
      els.intentState.classList.add("hidden");
    }
    els.badgeText.textContent = "Idle";
    els.badge.classList.remove("active");
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
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

function templateDurationLabel(template) {
  if (template.session_type === "pomodoro") {
    return `${template.focus_minutes || 25}/${template.break_minutes || 5} × ${template.cycles || 4}`;
  }
  return `${template.duration_minutes || 0}m`;
}

async function fetchTemplates() {
  try {
    const res = await api("GET", "/api/templates");
    if (res.status === "ok") {
      sessionTemplates = res.templates || [];
      renderTemplates();
    }
  } catch (e) {
    console.error("Failed to fetch templates:", e);
  }
}

function renderTemplates() {
  if (!els.mbTemplatesList) return;
  const section = document.getElementById("mbTemplatesSection");
  if (!section) return;

  if (els.mbTemplatesCount) els.mbTemplatesCount.textContent = `${sessionTemplates.length} saved`;
  els.mbTemplatesList.innerHTML = "";
  
  if (sessionTemplates.length === 0) {
    section.classList.add("hidden");
    return;
  }
  
  section.classList.remove("hidden");
  
  sessionTemplates.forEach((template) => {
    const chip = document.createElement("div");
    chip.className = "group-chip";
    chip.textContent = template.name || "Untitled";
    chip.style.cursor = "pointer";
    
    chip.addEventListener("click", () => {
      // Set Mode
      currentMode = template.mode || "blacklist";
      els.modeChips.forEach(b => b.classList.remove("active"));
      const activeModeBtn = Array.from(els.modeChips).find(b => b.dataset.mode === currentMode);
      if (activeModeBtn) activeModeBtn.classList.add("active");

      // Set Type
      currentType = template.session_type || "standard";
      els.typeChips.forEach(b => b.classList.remove("active"));
      const activeTypeBtn = Array.from(els.typeChips).find(b => b.dataset.type === currentType);
      if (activeTypeBtn) activeTypeBtn.classList.add("active");

      if (currentType === "pomodoro") {
        els.standardSection.classList.add("hidden");
        els.pomoSection.classList.remove("hidden");
        
        els.pomoFocus.value = template.focus_minutes || 25;
        els.pomoBreak.value = template.break_minutes || 5;
        els.pomoCycles.value = template.cycles || 4;
        
        els.pomoChips.forEach(b => b.classList.remove("active"));
      } else if (currentType === "rescue") {
        els.rescueDur.value = template.duration_minutes || 10;
      } else {
        els.standardSection.classList.remove("hidden");
        els.pomoSection.classList.add("hidden");
        
        els.durChips.forEach(b => b.classList.remove("active"));
        els.customMin.value = template.duration_minutes || 60;
        
        // Find matching dur chip if exact match
        const matchingChip = Array.from(els.durChips).find(b => parseInt(b.dataset.min) === (template.duration_minutes || 60));
        if (matchingChip) {
          matchingChip.classList.add("active");
          els.customMin.value = "";
        }
      }

      // Set Groups
      selectedGroups = template.groups || [];
      renderGroups();
    });
    
    els.mbTemplatesList.appendChild(chip);
  });
}


async function fetchGroups() {
  try {
    const res = await api("GET", "/api/groups");
    if (res.groups) {
      availableGroups = res.groups;
      renderGroups();
    }
    const resLists = await api("GET", "/api/lists");
    if (resLists.lists) {
      availableLists = resLists.lists;
    }
  } catch (e) {
    console.error("Failed to fetch groups or lists:", e);
  }
}

function renderGroups() {
  if (!els.groupGrid || !els.groupSection) return;

  const names = Object.keys(availableGroups);
  if (names.length === 0 || currentMode === "ban") {
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
      renderGroups();
      updateBlockDetails();
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

  // Block Details ────────────────────────────────────────────────────────────

  function computeBlockDetails() {
    const blockType = currentMode === "whitelist" ? "✅ Whitelist" : currentMode === "ban" ? "⛔ Ban" : "🚫 Blacklist";
    const sessionLabel = currentType === "pomodoro" ? "🍅 Pomodoro" : "⏱ Standard";

    let totalMinutes;
    let durationText;
    if (currentType === "pomodoro") {
      const focusMin = parseInt(els.pomoFocus.value) || 25;
      const breakMin = parseInt(els.pomoBreak.value) || 5;
      const cycles = parseInt(els.pomoCycles.value) || 4;
      totalMinutes = (focusMin + breakMin) * cycles;
      durationText = `${focusMin}m focus × ${cycles} cycles`;
    } else {
      const selectedDurChip = Array.from(els.durChips).find((c) =>
        c.classList.contains("active")
      );
      totalMinutes = selectedDurChip ? parseInt(selectedDurChip.dataset.min) : 120;
      if (els.customMin.value) {
        totalMinutes = parseInt(els.customMin.value) || 120;
      }
      const hrs = Math.floor(totalMinutes / 60);
      const mins = totalMinutes % 60;
      durationText = hrs > 0 ? `${hrs}h ${mins > 0 ? mins + "m" : ""}`.trim() : `${mins}m`;
    }

    const expiryDate = new Date(Date.now() + totalMinutes * 60000);
    let expiryHrs = expiryDate.getHours();
    const expiryMins = String(expiryDate.getMinutes()).padStart(2, "0");
    const ampm = expiryHrs >= 12 ? "PM" : "AM";
    expiryHrs = expiryHrs % 12 || 12;
    const expiryText = `${expiryHrs}:${expiryMins} ${ampm}`;

    let domainCount = "—";
    let groupText = "—";
    try {
      const uniqueDomains = new Set();
      const groupNames = Array.from(selectedGroups);
        
      if (groupNames.length > 0) {
        groupText = groupNames.join(", ");
      } else {
        groupText = "—";
      }

      for (const name of groupNames) {
        const domains = availableGroups[name];
        if (Array.isArray(domains)) {
          domains.forEach((d) => uniqueDomains.add(d));
        }
      }
      
      if (currentMode === "blacklist" && availableLists.blacklist) {
        availableLists.blacklist.forEach((d) => uniqueDomains.add(d));
      } else if (currentMode === "whitelist" && availableLists.whitelist) {
        availableLists.whitelist.forEach((d) => uniqueDomains.add(d));
      }
      
      domainCount = uniqueDomains.size > 0 ? `${uniqueDomains.size} domains` : "—";
    } catch {
      domainCount = "—";
      groupText = "—";
    }

    return { blockType, sessionType: sessionLabel, durationText, expiryText, domainCount, groupText };
  }

  function renderMenubarBlockDetails(details) {
    const setEl = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };
    setEl("mbDetailType", details.blockType);
    setEl("mbDetailSession", details.sessionType);
    setEl("mbDetailDuration", details.durationText);
    setEl("mbDetailExpiry", details.expiryText);
    setEl("mbDetailGroups", details.groupText);
    setEl("mbDetailDomains", details.domainCount);

    const errorEl = document.getElementById("mbBlockDetailsError");
    if (errorEl) errorEl.classList.add("hidden");
  }

  els.btnStart.addEventListener("click", () => {
    els.idleState.classList.add("hidden");
    const details = computeBlockDetails();
    renderMenubarBlockDetails(details);
    els.blockDetailsState.classList.remove("hidden");
  });

  if (els.mbBtnCancelDetails) {
    els.mbBtnCancelDetails.addEventListener("click", () => {
      els.blockDetailsState.classList.add("hidden");
      els.idleState.classList.remove("hidden");
    });
  }

  if (els.mbBtnConfirmDetails) {
    els.mbBtnConfirmDetails.addEventListener("click", () => {
      els.blockDetailsState.classList.add("hidden");
      els.intentState.classList.remove("hidden");
      els.intentPromptInput.value = "";
      const intentTasksInput = document.getElementById("intentTasksInput");
      if (intentTasksInput) intentTasksInput.value = "";
      els.intentPromptInput.focus();
    });
  }

  if (els.mbBlockDetailsRetry) {
    els.mbBlockDetailsRetry.addEventListener("click", async () => {
      await fetchGroups();
      const details = computeBlockDetails();
      renderMenubarBlockDetails(details);
    });
  }

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
        const confirmed = await waitForStatusConfirmation((status) =>
          sessionStatusMatchesPayload(status, payload),
        );
        if (!confirmed) {
          showNotificationFallback("Session request accepted; waiting for daemon confirmation.");
        }
      } else {
        showNotificationFallback(res.message || "Failed to start session.");
      }
    } catch (e) {
      console.error("Start failed:", e);
      showNotificationFallback("Communication failed.");
    } finally {
      els.btnIntentConfirm.innerHTML = originalIntentHTML;
      els.btnIntentConfirm.disabled = false;
      els.btnIntentConfirm.removeAttribute("aria-busy");
      isStarting = false;
      refresh();
    }
  });

  els.mbBtnRescue.addEventListener("click", async () => {
    const originalRescueHTML = els.mbBtnRescue.innerHTML;
    els.mbBtnRescue.innerHTML = '<span class="btn-spinner"></span> Activating...';
    els.mbBtnRescue.disabled = true;
    els.mbBtnRescue.setAttribute("aria-busy", "true");
    
    try {
      const dur = parseInt(els.rescueDur.value, 10) || 10;
      const payload = {
        duration: dur,
        mode: "whitelist",
        session_type: "rescue",
      };
      const res = await api("POST", "/api/start", payload);
      if (res.status === "ok") {
        const confirmed = await waitForStatusConfirmation((status) =>
          sessionStatusMatchesPayload(status, payload),
        );
        if (!confirmed) {
          showNotificationFallback("Rescue request accepted; waiting for daemon confirmation.");
        }
      } else {
        showNotificationFallback(res.message || "Failed to activate Rescue.");
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
          const confirmed = await waitForStatusConfirmation(stopStatusConfirmed);
          if (confirmed) {
            document.getElementById("unlockDialog").classList.add("hidden");
          } else {
            showNotificationFallback("Unlock accepted; waiting for daemon confirmation.");
          }
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

  // Continue Focus (cancel pending unlock)
  const mbBtnContinueFocus = $("#mbBtnContinueFocus");
  if (mbBtnContinueFocus) {
    mbBtnContinueFocus.addEventListener("click", async () => {
      mbBtnContinueFocus.disabled = true;
      try {
        const res = await api("POST", "/api/cancel-stop");
        if (res.status === "ok") {
          showNotificationFallback(res.message);
          refresh();
        } else {
          showNotificationFallback("Error: " + res.message);
        }
      } catch (err) {
        showNotificationFallback("Connection failed.");
      } finally {
        mbBtnContinueFocus.disabled = false;
      }
    });
  }
}

let globalPollInterval = null;

window.onPopoverShow = () => {
  isPopoverVisible = true;
  loadSettings();
  fetchGroups();
  refresh();
  connectSSE();
  // WP1: Reduced from 1s to 30s — SSE is primary; polling is fallback only
  if (!globalPollInterval) globalPollInterval = setInterval(refresh, 30000);
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
  isPopoverVisible = false;
  // Keep SSE active to drive the native menubar countdown via nativeCallback
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
  if (globalPollInterval) {
    clearInterval(globalPollInterval);
    globalPollInterval = null;
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  initEvents();

  // S8: Load settings and refresh status immediately, don't wait for onPopoverShow
  loadSettings();
  fetchGroups();
  fetchTemplates();
  // Wait for onPopoverShow to call refresh() and start globalPollInterval.
  // We only connect SSE so the native title updates!
  connectSSE();
});

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
      if (isPopoverVisible) {
        renderStatus(data);
      }
      
      // Instant Config Sync
      if (typeof _lastRevision === "undefined") {
        _lastRevision = data.state_revision;
      } else if (data.state_revision !== undefined && data.state_revision > _lastRevision) {
        _lastRevision = data.state_revision;
        // Fetch new configurations if the user changed them elsewhere
        fetchGroups();
        fetchTemplates();
        loadSettings();
      }

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
    eventSource = null;
    scheduleSSEReconnect();
  };
}
