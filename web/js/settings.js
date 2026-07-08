import { escapeHtml, extractDomain, showToast as sharedShowToast } from "../shared/utils.js";
import { api } from "../shared/api.js";

/**
 * ForcedFocus — Settings Client
 */

const $ = (sel) => document.querySelector(sel);

const normalizeNumerals = (str) => {
  if (typeof str !== 'string') return str;
  return str.replace(/[٠-٩]/g, d => "٠١٢٣٤٥٦٧٨٩".indexOf(d)).replace(/[٫]/g, '.');
};

const els = {
  settingsGrid: $("#settingsGrid"),
  soundLibrary: $("#soundLibrary"),
  btnSaveSettings: $("#btnSaveSettings"),
  toast: $("#toast"),
  fileInput: $("#fileInput"),
  btnTriggerUpload: $("#btnTriggerUpload"),
  btnToggleLibrary: $("#btnToggleLibrary"),
  libraryContent: $("#libraryContent"),
  uploadStatus: $("#uploadStatus"),
  groupList: $("#groupList"),
  btnNewGroup: $("#btnNewGroup"),
  groupModal: $("#groupModal"),
  groupNameInput: $("#groupNameInput"),
  groupDomainsInput: $("#groupDomainsInput"),
  btnSaveGroup: $("#btnSaveGroup"),
  btnCancelGroup: $("#btnCancelGroup"),
  groupModalTitle: $("#groupModalTitle"),
  navTabs: document.querySelectorAll(".nav-tab"),
  tabContents: document.querySelectorAll(".tab-content"),
  dropZone: $("#dropZone"),
  domainError: $("#domainError"),
  btnToggleSoundMapping: $("#btnToggleSoundMapping"),
  iconToggleSoundMapping: $("#iconToggleSoundMapping"),
  soundMappingContent: $("#soundMappingContent"),
};

let settings = {};
let availableSounds = [];
let availableGroups = {};
let previewAudio = null;
let currentPreviewBtn = null;

let eventSource = null;
let sseReconnectTimer = null;
let _lastRevision = undefined;
let _lastNextPrayerSeconds = null;

const showToast = (msg) => sharedShowToast(els.toast, msg);

function playPreview(filename, btnElement = null) {
  if (previewAudio) {
    previewAudio.pause();
    previewAudio = null;
  }

  if (currentPreviewBtn) {
    currentPreviewBtn.textContent = "▶";
    const wasSameBtn = (currentPreviewBtn === btnElement);
    currentPreviewBtn = null;
    if (wasSameBtn) {
      return;
    }
  }

  if (!filename) return;
  
  previewAudio = new Audio("/assets/sounds/" + encodeURIComponent(filename));
  
  if (btnElement) {
    currentPreviewBtn = btnElement;
    btnElement.textContent = "⏹";
    previewAudio.addEventListener("ended", () => {
      if (currentPreviewBtn === btnElement) {
        btnElement.textContent = "▶";
        currentPreviewBtn = null;
      }
    });
  }

  previewAudio.play().catch((e) => {
    console.error("Preview error:", e);
    if (currentPreviewBtn === btnElement && btnElement) {
      btnElement.textContent = "▶";
      currentPreviewBtn = null;
    }
  });
}

async function handleFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  if (!file.name.endsWith(".mp3")) {
    return showToast("Only .mp3 files are allowed.");
  }

  els.uploadStatus.textContent = "Uploading...";

  const reader = new FileReader();
  reader.onload = async () => {
    const base64 = reader.result.split(",")[1];
    try {
      const res = await api("POST", "/api/upload-sound", {
        filename: file.name,
        data: base64,
      });
      if (res.status === "ok") {
        showToast("Sound uploaded.");
        const soundsRes = await api("GET", "/api/sounds");
        if (soundsRes.sounds) {
          availableSounds = soundsRes.sounds;
          renderSettings();
          renderSoundLibrary();
        }
      } else {
        showToast("Error: " + res.message);
      }
    } catch (err) {
      showToast("Upload failed.");
    }
    els.uploadStatus.textContent = "";
    els.fileInput.value = "";
  };
  reader.readAsDataURL(file);
}

function renderSettings() {
  if (!settings) return;
  const labels = {
    sound_start: "Session Start",
    sound_rescue: "Rescue Mode",
    sound_unlock: "Unlock Request",
    sound_break: "Break Time",
    sound_end: "Session End",
    sound_scheduled: "Scheduled Session",
    sound_blocked: "Blocked Site Access",
    sound_prayer: "Prayer Time",
  };

  // R7: Use escapeHtml on all user-controlled data
  let html = "";
  for (const [key, label] of Object.entries(labels)) {
    const current = settings[key] || "";
        html += `
            <div class="flex items-center justify-between p-5 bg-black/20 rounded-2xl border border-white/5 hover:border-white/10 transition-colors">
                <label class="font-bold text-gray-200 text-base">${escapeHtml(label)}</label>
                <div class="relative">
                  <select class="bg-black/50 border border-white/10 text-gray-200 text-sm font-bold rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 block p-3 pr-10 outline-none appearance-none cursor-pointer hover:border-white/20 transition-colors" data-key="${escapeHtml(key)}">
                      <option value="">None</option>
                      ${availableSounds.map((s) => `<option value="${escapeHtml(s)}" ${s === current ? "selected" : ""}>${escapeHtml(s)}</option>`).join("")}
                  </select>
                  <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-gray-400">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                  </div>
                </div>
            </div>
        `;
  }
  els.settingsGrid.innerHTML = html;

  // Notifications and Goals
  const intentEnabled = document.getElementById("intentNotifEnabled");
  const intentInterval = document.getElementById("intentNotifInterval");
  const dailyFocusGoal = document.getElementById("dailyFocusGoalHours");
  if (intentEnabled)
    intentEnabled.checked = settings.intent_notification_enabled !== false;
  if (intentInterval)
    intentInterval.value = settings.intent_notification_interval || 15;
  if (dailyFocusGoal)
    dailyFocusGoal.value = settings.daily_focus_goal_hours || "";
    
  // Prayer Times
  const prayerEnabled = document.getElementById("prayerBlockEnabled");
  const prayerLat = document.getElementById("prayerLatitude");
  const prayerLon = document.getElementById("prayerLongitude");
  const prayerMethod = document.getElementById("prayerMethod");
  const prayerMinBefore = document.getElementById("prayerMinutesBefore");
  const prayerMinAfter = document.getElementById("prayerMinutesAfter");
  
  if (prayerEnabled) {
    prayerEnabled.checked = settings.prayer_block_enabled || false;
    updatePrayerCheckboxState();
  }
  if (prayerLat) prayerLat.value = settings.prayer_latitude ?? 0;
  if (prayerLon) prayerLon.value = settings.prayer_longitude ?? 0;
  if (prayerMethod) prayerMethod.value = settings.prayer_method ?? 5;
  if (prayerMinBefore) prayerMinBefore.value = settings.prayer_minutes_before ?? 10;
  if (prayerMinAfter) prayerMinAfter.value = settings.prayer_minutes_after ?? 30;
}

function updatePrayerCheckboxState() {
  const prayerEnabled = document.getElementById("prayerBlockEnabled");
  if (prayerEnabled) {
    // Disable checkbox if within 30 minutes of next prayer and it's currently enabled
    if (prayerEnabled.checked && _lastNextPrayerSeconds !== null && _lastNextPrayerSeconds <= 1800) {
      prayerEnabled.disabled = true;
      prayerEnabled.title = "Cannot disable prayer mode within 30 minutes of a prayer time.";
      prayerEnabled.parentElement.title = "Cannot disable prayer mode within 30 minutes of a prayer time.";
    } else {
      prayerEnabled.disabled = false;
      prayerEnabled.title = "";
      prayerEnabled.parentElement.title = "";
    }
  }
}

async function saveSettings() {
  const btn = els.btnSaveSettings;
  if (btn) btn.disabled = true;
  const originalText = btn ? btn.textContent : "";
  if (btn) btn.textContent = "Saving...";

  try {
    const newSettings = {};
    els.settingsGrid.querySelectorAll("select").forEach((sel) => {
      newSettings[sel.dataset.key] = sel.value;
    });

    const intentEnabled = document.getElementById("intentNotifEnabled");
    const intentInterval = document.getElementById("intentNotifInterval");
    const dailyFocusGoal = document.getElementById("dailyFocusGoalHours");
    if (intentEnabled)
      newSettings.intent_notification_enabled = intentEnabled.checked;
    if (intentInterval) {
      const parsedInterval = parseInt(intentInterval.value, 10);
      if (!Number.isInteger(parsedInterval) || parsedInterval < 1 || parsedInterval > 1440) {
        showToast("Notification interval must be 1-1440 minutes.");
        return;
      }
      newSettings.intent_notification_interval = parsedInterval;
    }
    if (dailyFocusGoal && dailyFocusGoal.value.trim() !== "") {
      const parsedHours = parseFloat(normalizeNumerals(dailyFocusGoal.value));
      if (!isNaN(parsedHours) && parsedHours > 0) {
        newSettings.daily_focus_goal_hours = parsedHours;
      }
    } else if (dailyFocusGoal) {
      newSettings.daily_focus_goal_hours = 0;
    }

    // Prayer settings
    const prayerEnabled = document.getElementById("prayerBlockEnabled");
    const prayerLat = document.getElementById("prayerLatitude");
    const prayerLon = document.getElementById("prayerLongitude");
    const prayerMethod = document.getElementById("prayerMethod");
    const prayerMinBefore = document.getElementById("prayerMinutesBefore");
    const prayerMinAfter = document.getElementById("prayerMinutesAfter");

    if (prayerEnabled) newSettings.prayer_block_enabled = prayerEnabled.checked;
    if (prayerLat) newSettings.prayer_latitude = parseFloat(normalizeNumerals(prayerLat.value)) || 0;
    if (prayerLon) newSettings.prayer_longitude = parseFloat(normalizeNumerals(prayerLon.value)) || 0;
    if (prayerMethod) newSettings.prayer_method = parseInt(prayerMethod.value, 10) || 5;
    // Helper to safely parse and clamp minutes (0 to 120)
    const parseMinutes = (val) => {
      const parsed = parseInt(normalizeNumerals(val), 10);
      return Math.min(120, Math.max(0, isNaN(parsed) ? 0 : parsed));
    };

    if (prayerMinBefore) newSettings.prayer_minutes_before = parseMinutes(prayerMinBefore.value);
    if (prayerMinAfter) newSettings.prayer_minutes_after = parseMinutes(prayerMinAfter.value);

    const res = await api("POST", "/api/settings", { settings: newSettings });
    if (res.status === "ok") {
      showToast("Settings saved.");
      await fetchData(); // Instant update
    } else {
      showToast("Error: " + res.message);
    }
  } catch (e) {
    showToast("Failed to save settings.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

async function fetchData() {
  try {
    const [settingsRes, soundsRes, groupsRes] = await Promise.all([
      api("GET", "/api/settings"),
      api("GET", "/api/sounds"),
      api("GET", "/api/groups"),
    ]);

    if (settingsRes.settings) settings = settingsRes.settings;
    if (soundsRes.sounds) availableSounds = soundsRes.sounds;
    if (groupsRes.groups) availableGroups = groupsRes.groups;

    renderSettings();
    renderSoundLibrary();
    renderGroups();
  } catch (e) {
    console.error("Fetch error:", e);
  }
}

function connectSSE() {
  if (sseReconnectTimer) {
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = null;
  }
  if (eventSource) eventSource.close();
  
  eventSource = new EventSource("/api/stream");
  
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      
      let prayerTimeChanged = false;
      if (data.next_prayer_seconds !== _lastNextPrayerSeconds) {
        _lastNextPrayerSeconds = data.next_prayer_seconds;
        prayerTimeChanged = true;
      }

      // Instant Config Sync
      if (typeof _lastRevision === "undefined") {
        _lastRevision = data.state_revision;
      } else if (data.state_revision !== undefined && data.state_revision > _lastRevision) {
        _lastRevision = data.state_revision;
        // Silently fetch configurations if the user changed them elsewhere
        fetchData();
      } else if (prayerTimeChanged) {
        // Just re-render checkbox state, not the whole settings UI
        updatePrayerCheckboxState();
      }
    } catch (err) {
      console.error("SSE parse error:", err);
    }
  };
  
  eventSource.onerror = () => {
    console.warn("SSE connection lost. Reconnecting in 3s...");
    eventSource.close();
    eventSource = null;
    sseReconnectTimer = setTimeout(connectSSE, 3000);
  };
}

async function init() {
  await fetchData();
  connectSSE();

  // Attach event listeners
  els.btnSaveSettings.addEventListener("click", saveSettings);
  if(els.btnTriggerUpload) els.btnTriggerUpload.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", handleFileUpload);
  
  const btnGetLocation = document.getElementById("btnGetLocation");
  if (btnGetLocation) {
    btnGetLocation.addEventListener("click", () => {
      if (!navigator.geolocation) {
        showToast("Geolocation is not supported by your browser.");
        return;
      }
      const originalText = btnGetLocation.innerHTML;
      btnGetLocation.innerHTML = "Fetching...";
      btnGetLocation.disabled = true;
      navigator.geolocation.getCurrentPosition(
        (position) => {
          document.getElementById("prayerLatitude").value = position.coords.latitude;
          document.getElementById("prayerLongitude").value = position.coords.longitude;
          btnGetLocation.innerHTML = originalText;
          btnGetLocation.disabled = false;
          showToast("Location updated successfully.");
        },
        (error) => {
          showToast("Unable to retrieve your location.");
          btnGetLocation.innerHTML = originalText;
          btnGetLocation.disabled = false;
        }
      );
    });
  }
  
  // Drag and Drop
  const dz = els.dropZone;
  if (dz) {
    dz.addEventListener('dragover', (e) => {
      e.preventDefault();
      dz.classList.add('bg-indigo-500/10', 'border-indigo-400');
    });
    dz.addEventListener('dragleave', (e) => {
      e.preventDefault();
      dz.classList.remove('bg-indigo-500/10', 'border-indigo-400');
    });
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('bg-indigo-500/10', 'border-indigo-400');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        els.fileInput.files = e.dataTransfer.files;
        handleFileUpload({ target: els.fileInput });
      }
    });
  }

  // Tabs
  els.navTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      els.navTabs.forEach(t => {
        t.classList.remove("active", "bg-indigo-500/15", "border-indigo-500/30", "text-white", "shadow-[0_0_20px_rgba(99,102,241,0.1)]");
        t.classList.add("text-gray-400", "border-transparent", "hover:bg-white/5", "hover:text-white");
      });
      tab.classList.add("active", "bg-indigo-500/15", "border-indigo-500/30", "text-white", "shadow-[0_0_20px_rgba(99,102,241,0.1)]");
      tab.classList.remove("text-gray-400", "border-transparent", "hover:bg-white/5", "hover:text-white");
      
      els.tabContents.forEach(c => c.classList.remove("active"));
      const targetId = tab.getAttribute("data-target");
      const targetEl = document.getElementById(targetId);
      if(targetEl) targetEl.classList.add("active");
    });
  });

  // Sound Library Listeners
  els.soundLibrary.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-icon");
    if (!btn) return;
    const sound = btn.dataset.sound;
    if (btn.classList.contains("play-sound")) playPreview(sound, btn);
    if (btn.classList.contains("delete-sound")) deleteSound(sound, btn);
  });

  els.btnToggleLibrary.addEventListener("click", () => {
    els.btnToggleLibrary.classList.toggle("open");
    els.libraryContent.classList.toggle("hidden");
  });

  if (els.btnToggleSoundMapping) {
    els.btnToggleSoundMapping.addEventListener("click", () => {
      els.soundMappingContent.classList.toggle("hidden");
      els.iconToggleSoundMapping.classList.toggle("rotate-180");
    });
  }

  // Groups Listeners
  els.btnNewGroup.addEventListener("click", () => openGroupModal());
  els.btnCancelGroup.addEventListener("click", () =>
    els.groupModal.classList.add("hidden"),
  );
  els.btnSaveGroup.addEventListener("click", saveGroup);

  els.groupList.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-group-action");
    if (!btn) return;
    const action = btn.dataset.action;
    const name = btn.dataset.name;
    if (action === "edit") openGroupModal(name);
    if (action === "delete") deleteGroup(name, btn);
  });
  
  if (els.groupDomainsInput) {
    const formatInput = (e) => {
      const val = e.target.value;
      if (!val.trim()) return;
      const cleanedDomains = val
        .split(/[\n, ]+/)
        .map(d => extractDomain(d))
        .filter(d => d.length > 0);
      e.target.value = cleanedDomains.join("\n");
    };
    
    els.groupDomainsInput.addEventListener("blur", formatInput);
    
    // Clear any previous error states immediately on input
    els.groupDomainsInput.addEventListener("input", () => {
      if (els.domainError) els.domainError.classList.add("hidden");
      if (els.btnSaveGroup) {
        els.btnSaveGroup.disabled = false;
        els.btnSaveGroup.classList.remove("opacity-50", "cursor-not-allowed");
      }
    });
  }

  els.settingsGrid.addEventListener("change", (e) => {
    if (e.target.tagName === "SELECT") {
      playPreview(e.target.value);
    }
  });
}

function renderSoundLibrary() {
  if (availableSounds.length === 0) {
    els.soundLibrary.innerHTML =
      '<div class="empty-state">No sounds available.</div>';
    return;
  }

  let html = "";
  for (const sound of availableSounds) {
    const safeSound = escapeHtml(sound);
        html += `
            <div class="flex items-center justify-between p-3.5 border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors rounded-xl group">
                <div class="flex items-center gap-4">
                    <button class="btn-icon play-sound w-10 h-10 flex items-center justify-center rounded-full bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500 hover:text-white transition-all hover:scale-105 active:scale-95" data-sound="${safeSound}" title="Play">▶</button>
                    <div class="text-sm font-bold text-gray-200 truncate max-w-[200px]" title="${safeSound}">${safeSound}</div>
                </div>
                <button class="btn-icon delete delete-sound w-10 h-10 flex items-center justify-center rounded-full bg-red-500/10 text-red-400 hover:bg-red-500 hover:text-white transition-all opacity-0 group-hover:opacity-100 hover:scale-105 active:scale-95" data-sound="${safeSound}" title="Delete">✕</button>
            </div>
        `;
  }
  els.soundLibrary.innerHTML = html;
}

async function deleteSound(filename, button = null) {
  if (!confirm(`Delete sound "${filename}"?`)) return;
  if (button) button.disabled = true;

  try {
    const res = await api("POST", "/api/delete-sound", { filename });
    if (res.status === "ok") {
      showToast(`Sound "${filename}" deleted.`);
      const soundsRes = await api("GET", "/api/sounds");
      if (soundsRes.sounds) {
        availableSounds = soundsRes.sounds;
        renderSettings();
        renderSoundLibrary();
      }
    } else {
      showToast("Error: " + res.message);
    }
  } catch (e) {
    showToast("Failed to delete sound.");
  } finally {
    if (button) button.disabled = false;
  }
}

function renderGroups() {
  if (Object.keys(availableGroups).length === 0) {
    els.groupList.innerHTML =
      '<div class="empty-state">No groups created yet.</div>';
    return;
  }

  // R7: Use escapeHtml on all group names to prevent XSS
  let html = "";
  for (const [name, domains] of Object.entries(availableGroups)) {
    const safeName = escapeHtml(name);
        html += `
            <div class="bg-black/20 p-6 rounded-3xl border border-white/5 flex flex-col justify-between transition-all hover:border-white/10 hover:-translate-y-1 hover:shadow-2xl group">
                <div class="mb-6">
                    <div class="font-bold text-white text-xl">${safeName}</div>
                    <div class="text-xs font-bold text-indigo-400 mt-2 tracking-wide uppercase">${domains.length} domains</div>
                </div>
                <div class="flex gap-3">
                    <button class="btn-group-action flex-1 py-3 rounded-xl bg-white/5 hover:bg-white/10 border border-transparent hover:border-white/10 text-gray-300 text-sm font-bold transition-all hover:scale-105 active:scale-95" data-action="edit" data-name="${safeName}">✏️ Edit</button>
                    <button class="btn-group-action flex-1 py-3 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-transparent hover:border-red-500/20 text-red-400 text-sm font-bold transition-all hover:scale-105 active:scale-95" data-action="delete" data-name="${safeName}">🗑️ Delete</button>
                </div>
            </div>
        `;
  }
  els.groupList.innerHTML = html;
}

function openGroupModal(name = "") {
  if (name) {
    els.groupModalTitle.textContent = "🛡️ Edit Group";
    els.groupNameInput.value = name;
    els.groupNameInput.disabled = true;
    els.groupDomainsInput.value = availableGroups[name].join("\n");
  } else {
    els.groupModalTitle.textContent = "🛡️ New Group";
    els.groupNameInput.value = "";
    els.groupNameInput.disabled = false;
    els.groupDomainsInput.value = "";
  }
  els.groupModal.classList.remove("hidden");
}

async function saveGroup() {
  const name = els.groupNameInput.value.trim();
  const domainsText = els.groupDomainsInput.value.trim();
  if (!name) return showToast("Please enter a group name.");

  const domains = domainsText
    .split(/[\n, ]+/)
    .map((d) => extractDomain(d))
    .filter((d) => d.length > 0);

  if (domains.length === 0) return showToast("Please add at least one domain.");

  els.btnSaveGroup.disabled = true;
  const originalText = els.btnSaveGroup.textContent;
  els.btnSaveGroup.textContent = "Saving...";
  try {
    const res = await api("POST", "/api/groups", { name, domains });
    if (res.status === "ok") {
      els.groupModal.classList.add("hidden");
      showToast(`Group "${name}" saved.`);
      // S5: Re-fetch from server instead of optimistic update
      const groupsRes = await api("GET", "/api/groups");
      if (groupsRes.groups) {
        availableGroups = groupsRes.groups;
        renderGroups();
      }
    } else {
      showToast("Error: " + res.message);
    }
  } catch (e) {
    showToast("Failed to save group.");
  } finally {
    els.btnSaveGroup.disabled = false;
    els.btnSaveGroup.textContent = originalText;
  }
}

async function deleteGroup(name, button = null) {
  if (!confirm(`Delete group "${name}"?`)) return;
  if (button) button.disabled = true;

  try {
    const res = await api("DELETE", `/api/groups/${encodeURIComponent(name)}`);
    if (res.status === "ok") {
      delete availableGroups[name];
      renderGroups();
      showToast(`Group "${name}" removed.`);
    } else {
      showToast("Error: " + res.message);
    }
  } catch (e) {
    showToast("Failed to delete group.");
  } finally {
    if (button) button.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", init);
