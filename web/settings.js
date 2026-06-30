/**
 * ForcedFocus — Settings Client
 */

const $ = (sel) => document.querySelector(sel);

// R7: HTML escaping for safe rendering
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
};

let settings = {};
let availableSounds = [];
let availableGroups = {};
let previewAudio = null;
let apiToken = "";

const activeRequests = new Map();

async function api(method, endpoint, body = null) {
  const headers = { "Content-Type": "application/json" };
  if (apiToken) headers["X-API-Token"] = apiToken;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  // Flow Reliability: Prevent GET request race conditions and overlap
  const requestKey = method + ":" + (endpoint || "");
  let controller = null;
  if (method === "GET") {
    if (activeRequests.has(requestKey)) {
      activeRequests.get(requestKey).abort();
    }
    controller = new AbortController();
    opts.signal = controller.signal;
    activeRequests.set(requestKey, controller);
  }
  try {
    const res = await fetch(endpoint, opts);
    // S4: Auto-refresh token on 401 (daemon restarted)
    if (res.status === 401) {
      await loadApiToken();
      if (apiToken) headers["X-API-Token"] = apiToken;
      const retry = await fetch(endpoint, { method, headers, body: opts.body });
      return await retry.json();
    }
    return await res.json();
  } catch (err) {
    if (err.name === "AbortError") {
      return { status: "aborted", message: "Request superseded." };
    }
    console.error("API Error:", err);
    return { status: "error", message: "Communication failed." };
  } finally {
    if (method === "GET" && activeRequests.get(requestKey) === controller) {
      activeRequests.delete(requestKey);
    }
  }
}

async function loadApiToken() {
  if (window.apiToken) {
    apiToken = window.apiToken;
  }
}

function showToast(msg) {
  els.toast.textContent = msg;
  els.toast.classList.remove("hidden");
  setTimeout(() => els.toast.classList.add("hidden"), 3000);
}

function playPreview(filename) {
  if (previewAudio) {
    previewAudio.pause();
    previewAudio = null;
  }
  if (!filename) return;
  previewAudio = new Audio("/sounds/" + encodeURIComponent(filename));
  previewAudio.play().catch((e) => console.log("Preview error:", e));
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
    sound_prayer: "Prayer Mode (Adhan)",
  };

  // R7: Use escapeHtml on all user-controlled data
  let html = "";
  for (const [key, label] of Object.entries(labels)) {
    const current = settings[key] || "";
        html += `
            <div class="settings-item">
                <label>${escapeHtml(label)}</label>
                <select class="custom-select" data-key="${escapeHtml(key)}">
                    <option value="">None</option>
                    ${availableSounds.map((s) => `<option value="${escapeHtml(s)}" ${s === current ? "selected" : ""}>${escapeHtml(s)}</option>`).join("")}
                </select>
            </div>
        `;
  }
  els.settingsGrid.innerHTML = html;

  // Notifications and Goals
  const intentEnabled = document.getElementById("intentNotifEnabled");
  const intentInterval = document.getElementById("intentNotifInterval");
  const dailyFocusGoal = document.getElementById("dailyFocusGoalHours");
  const prayerEnabled = document.getElementById("prayerEnabled");
  if (intentEnabled)
    intentEnabled.checked = settings.intent_notification_enabled !== false;
  if (intentInterval)
    intentInterval.value = settings.intent_notification_interval || 15;
  if (dailyFocusGoal)
    dailyFocusGoal.value = settings.daily_focus_goal_hours || "";
  if (prayerEnabled)
    prayerEnabled.checked = settings.prayer_enabled !== false;

  // Prayer location status
  const locationStatus = document.getElementById("locationStatus");
  if (locationStatus) {
    const lat = settings.prayer_latitude;
    const lng = settings.prayer_longitude;
    if (lat != null && lng != null) {
      locationStatus.textContent = `📍 ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      locationStatus.style.color = "var(--color-success, #4ade80)";
    } else {
      locationStatus.textContent = "⚠️ Not set";
      locationStatus.style.color = "var(--color-warning, #fbbf24)";
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
    const prayerEnabled = document.getElementById("prayerEnabled");
    if (intentEnabled)
      newSettings.intent_notification_enabled = intentEnabled.checked;
    if (intentInterval) {
      const parsedInterval = parseInt(intentInterval.value, 10);
      if (!Number.isInteger(parsedInterval) || parsedInterval < 1 || parsedInterval > 1440) {
        showToast("Notification interval must be 1-1440 minutes.");
        btn.textContent = originalText;
        btn.disabled = false;
        return;
      }
      newSettings.intent_notification_interval = parsedInterval;
    }
    if (dailyFocusGoal && dailyFocusGoal.value.trim() !== "") {
      const parsedHours = parseFloat(dailyFocusGoal.value);
      if (!isNaN(parsedHours) && parsedHours > 0) {
        newSettings.daily_focus_goal_hours = parsedHours;
      }
    } else if (dailyFocusGoal) {
      newSettings.daily_focus_goal_hours = 0;
    }
    if (prayerEnabled) {
      newSettings.prayer_enabled = prayerEnabled.checked;
    }

    const res = await api("POST", "/api/settings", { settings: newSettings });
    if (res.status === "ok") {
      showToast("Settings saved.");
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

async function detectLocation() {
  const btn = document.getElementById("btnDetectLocation");
  const statusEl = document.getElementById("locationStatus");
  if (!btn) return;

  if (!navigator.geolocation) {
    showToast("Geolocation is not supported by your browser.");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Detecting…";
  if (statusEl) {
    statusEl.textContent = "🔍 Detecting…";
    statusEl.style.color = "";
  }

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      try {
        const res = await api("POST", "/api/settings", {
          settings: { prayer_latitude: lat, prayer_longitude: lng },
        });
        if (res.status === "ok") {
          settings.prayer_latitude = lat;
          settings.prayer_longitude = lng;
          if (statusEl) {
            statusEl.textContent = `📍 ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
            statusEl.style.color = "var(--color-success, #4ade80)";
          }
          showToast("Location saved and prayer times updated successfully.");
        } else {
          showToast("Error saving location: " + (res.message || "Unknown error"));
          if (statusEl) {
            statusEl.textContent = "❌ Save failed";
            statusEl.style.color = "var(--color-error, #f87171)";
          }
        }
      } catch (e) {
        showToast("Failed to save location.");
        if (statusEl) {
          statusEl.textContent = "❌ Save failed";
          statusEl.style.color = "var(--color-error, #f87171)";
        }
      } finally {
        btn.disabled = false;
        btn.textContent = "📍 Detect Location";
      }
    },
    (error) => {
      btn.disabled = false;
      btn.textContent = "📍 Detect Location";
      let msg = "Location detection failed.";
      if (error.code === error.PERMISSION_DENIED) {
        msg = "Location permission denied. Please allow location access in your browser.";
      } else if (error.code === error.POSITION_UNAVAILABLE) {
        msg = "Location information is unavailable.";
      } else if (error.code === error.TIMEOUT) {
        msg = "Location request timed out. Try again.";
      }
      showToast(msg);
      if (statusEl) {
        statusEl.textContent = "⚠️ Not set";
        statusEl.style.color = "var(--color-warning, #fbbf24)";
      }
    },
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

async function init() {
  await loadApiToken();
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
    console.error("Init error:", e);
  }

  // Sidebar Navigation Logic
  const navItems = document.querySelectorAll(".settings-sidebar .nav-item");
  const panes = document.querySelectorAll(".settings-pane");

  navItems.forEach(item => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      
      // Remove active from all nav items
      navItems.forEach(nav => nav.classList.remove("active"));
      // Hide all panes
      panes.forEach(pane => pane.classList.remove("active"));
      
      // Add active to clicked item
      item.classList.add("active");
      
      // Show target pane
      const targetId = item.getAttribute("data-target");
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add("active");
      }
    });
  });

  // Attach event listeners
  els.btnSaveSettings.addEventListener("click", saveSettings);
  els.btnTriggerUpload.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", handleFileUpload);

  // Prayer location detection
  const btnDetect = document.getElementById("btnDetectLocation");
  if (btnDetect) btnDetect.addEventListener("click", detectLocation);

  // Sound Library Listeners
  els.soundLibrary.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-icon");
    if (!btn) return;
    const sound = btn.dataset.sound;
    if (btn.classList.contains("play-sound")) playPreview(sound);
    if (btn.classList.contains("delete-sound")) deleteSound(sound, btn);
  });

  els.btnToggleLibrary.addEventListener("click", () => {
    els.btnToggleLibrary.classList.toggle("open");
    els.libraryContent.classList.toggle("hidden");
  });

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
            <div class="sound-row">
                <div class="sound-main">
                    <button class="btn-icon play-sound" data-sound="${safeSound}" title="Play" aria-label="Play ${safeSound}">▶️</button>
                    <div class="sound-info" title="${safeSound}">${safeSound}</div>
                </div>
                <div class="sound-actions">
                    <button class="btn-icon delete delete-sound" data-sound="${safeSound}" title="Delete" aria-label="Delete ${safeSound}">🗑️</button>
                </div>
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
            <div class="group-card">
                <div class="group-info">
                    <div class="group-name">${safeName}</div>
                    <div class="group-meta">${domains.length} domains</div>
                </div>
                <div class="group-actions">
                    <button class="btn-group-action btn-icon" data-action="edit" data-name="${safeName}" title="Edit Group" aria-label="Edit group ${safeName}">✏️</button>
                    <button class="btn-group-action btn-icon delete" data-action="delete" data-name="${safeName}" title="Delete Group" aria-label="Delete group ${safeName}">🗑️</button>
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
    .map((d) => d.trim())
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
