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
  if (method !== "GET" && apiToken) headers["X-API-Token"] = apiToken;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  // Flow Reliability: Prevent GET request race conditions and overlap
  let requestKey = method + ":" + (endpoint || "");
  if (method === "GET") {
    if (activeRequests.has(requestKey)) {
      activeRequests.get(requestKey).abort();
    }
    const controller = new AbortController();
    opts.signal = controller.signal;
    activeRequests.set(requestKey, controller);
  }
  try {
    const res = await fetch(endpoint, opts);
    // S4: Auto-refresh token on 401 (daemon restarted)
    if (res.status === 401 && method !== "GET") {
      await loadApiToken();
      headers["X-API-Token"] = apiToken;
      const retry = await fetch(endpoint, { method, headers, body: opts.body });
      return await retry.json();
    }
    const data = await res.json();
    if (method === "GET") activeRequests.delete(requestKey);
    return data;
  } catch (err) {
    if (err.name === "AbortError") return new Promise(() => {});
    console.error("API Error:", err);
    return { status: "error", message: "Communication failed." };
  }
}

async function loadApiToken() {
  try {
    const res = await fetch("/api/token");
    const data = await res.json();
    if (data.token) apiToken = data.token;
  } catch (e) {
    console.error("Token load failed:", e);
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

  // Notifications
  const intentEnabled = document.getElementById("intentNotifEnabled");
  const intentInterval = document.getElementById("intentNotifInterval");
  if (intentEnabled)
    intentEnabled.checked = settings.intent_notification_enabled !== false;
  if (intentInterval)
    intentInterval.value = settings.intent_notification_interval || 15;
}

async function saveSettings() {
  const btn = document.querySelector(".settings-footer .primary-btn");
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
    if (intentEnabled)
      newSettings.intent_notification_enabled = intentEnabled.checked;
    if (intentInterval)
      newSettings.intent_notification_interval = parseInt(intentInterval.value);

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

  // Attach event listeners
  els.btnSaveSettings.addEventListener("click", saveSettings);
  els.btnTriggerUpload.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", handleFileUpload);

  // Sound Library Listeners
  els.soundLibrary.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-icon");
    if (!btn) return;
    const sound = btn.dataset.sound;
    if (btn.classList.contains("play-sound")) playPreview(sound);
    if (btn.classList.contains("delete-sound")) deleteSound(sound);
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
    if (action === "delete") deleteGroup(name);
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
      '<div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">No sounds available.</div>';
    return;
  }

  let html = "";
  for (const sound of availableSounds) {
    const safeSound = escapeHtml(sound);
    html += `
            <div class="sound-row">
                <div class="sound-main">
                    <button class="btn-icon play-sound" data-sound="${safeSound}" title="Play">▶️</button>
                    <div class="sound-info" title="${safeSound}">${safeSound}</div>
                </div>
                <div class="sound-actions">
                    <button class="btn-icon delete delete-sound" data-sound="${safeSound}" title="Delete">🗑️</button>
                </div>
            </div>
        `;
  }
  els.soundLibrary.innerHTML = html;
}

async function deleteSound(filename) {
  if (!confirm(`Delete sound "${filename}"?`)) return;

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
  }
}

function renderGroups() {
  if (Object.keys(availableGroups).length === 0) {
    els.groupList.innerHTML =
      '<div style="color: var(--text-muted); font-size: 13px; text-align: center; padding: 20px;">No groups created yet.</div>';
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
                    <button class="btn-group-action btn-icon" data-action="edit" data-name="${safeName}" title="Edit Group">✏️</button>
                    <button class="btn-group-action btn-icon delete" data-action="delete" data-name="${safeName}" title="Delete Group">🗑️</button>
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
  }
}

async function deleteGroup(name) {
  if (!confirm(`Delete group "${name}"?`)) return;

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
  }
}

document.addEventListener("DOMContentLoaded", init);
