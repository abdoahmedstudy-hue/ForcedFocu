/**
 * ForcedFocus Chrome Extension — Background Service Worker
 * Actively blocks blacklisted domains at the browser level using
 * declarativeNetRequest, preventing bypass via Chrome's Secure DNS.
 * Includes analytics, retry logic, adaptive polling, and state persistence.
 */

const API = "http://127.0.0.1:7070";
const POLL_INTERVAL = 3000;
const RULE_ID_START = 1000;
const MAX_RETRY_ATTEMPTS = 3;
const RETRY_DELAY = 2000;

// State management — persisted via chrome.storage.session to survive SW suspension
let lastActive = false;
let lastMode = null;
let lastPhase = null; // S3: Track pomodoro phase for change broadcasts
let connectionAttempts = 0;
let isRetrying = false;
let syncInProgress = false; // P4: Guard against cascading syncs

// Analytics
let analytics = {
  blockedRequests: 0,
  allowedRequests: 0,
  startTime: Date.now(),
};

// S4: Debounced analytics persistence
let analyticsFlushTimer = null;

// P3: Cached status to reduce daemon requests from multiple blocked tabs
let cachedStatus = null;
let cacheTimestamp = 0;
const CACHE_TTL = 2000;

// ── State Persistence (S2) ────────────────────────────────────────────────────

async function loadState() {
  try {
    const result = await chrome.storage.session.get([
      "lastActive",
      "lastMode",
      "lastPhase",
    ]);
    lastActive = result.lastActive || false;
    lastMode = result.lastMode || null;
    lastPhase = result.lastPhase || null;
  } catch (e) {
    // storage.session may not be available in older Chrome versions
    console.warn("[ForcedFocus] Could not load session state:", e);
  }
}

async function saveState() {
  try {
    await chrome.storage.session.set({ lastActive, lastMode, lastPhase });
  } catch (e) {
    // Non-critical — state will just be re-synced on next poll
  }
}

// ── Utility Functions ─────────────────────────────────────────────────────────

function log(message, level = "info") {
  const timestamp = new Date().toISOString();
  console.log(`[ForcedFocus][${timestamp}][${level.toUpperCase()}] ${message}`);
}

function isErrorRecoverable(error) {
  if (error instanceof TypeError && error.message.includes("fetch")) {
    return true;
  }
  if (error.name === "AbortError") {
    return true;
  }
  return false;
}

async function fetchWithRetry(
  url,
  options = {},
  maxRetries = MAX_RETRY_ATTEMPTS,
) {
  for (let i = 0; i <= maxRetries; i++) {
    try {
      const response = await fetch(url, {
        ...options,
        signal: AbortSignal.timeout(3000), // 3s timeout (reduced from 5s to limit P4 blocking)
      });
      return response;
    } catch (error) {
      if (i === maxRetries || !isErrorRecoverable(error)) {
        throw error;
      }
      log(
        `Fetch attempt ${i + 1} failed: ${error.message}. Retrying in ${RETRY_DELAY}ms...`,
        "warn",
      );
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY));
    }
  }
}

// ── Browser Cache Management ──────────────────────────────────────────────────

async function clearBrowserCache() {
  log("Clearing browser cache and service workers...");
  try {
    await chrome.browsingData.remove(
      {
        since: 0,
      },
      {
        cache: true,
        cacheStorage: true,
        serviceWorkers: true,
      },
    );
    log("Cache and service workers cleared successfully.");
  } catch (err) {
    log(`Failed to clear cache: ${err.message}`, "error");
  }
}

// ── Analytics ─────────────────────────────────────────────────────────────────

function recordBlockedRequest(domain) {
  analytics.blockedRequests++;
  // S4: Batch writes — flush every 5 seconds instead of every request
  if (!analyticsFlushTimer) {
    analyticsFlushTimer = setTimeout(() => {
      chrome.storage.local.set({ analytics });
      analyticsFlushTimer = null;
    }, 5000);
  }
}

function recordAllowedRequest(domain) {
  analytics.allowedRequests++;
}

// ── Rule Management ───────────────────────────────────────────────────────────

async function getDynamicRules() {
  try {
    return await chrome.declarativeNetRequest.getDynamicRules();
  } catch (err) {
    log(`Failed to get dynamic rules: ${err.message}`, "error");
    return [];
  }
}

async function updateDynamicRules(addRules = [], removeRuleIds = []) {
  try {
    await chrome.declarativeNetRequest.updateDynamicRules({
      addRules,
      removeRuleIds,
    });
    log(
      `Updated dynamic rules: ${addRules.length} added, ${removeRuleIds.length} removed`,
    );
  } catch (err) {
    log(`Failed to update dynamic rules: ${err.message}`, "error");
    throw err;
  }
}

// ── Block Rule Generation ─────────────────────────────────────────────────────

const ALL_RESOURCE_TYPES = [
  "main_frame",
  "sub_frame",
  "stylesheet",
  "script",
  "image",
  "font",
  "object",
  "xmlhttprequest",
  "ping",
  "csp_report",
  "media",
  "websocket",
  "webbundle",
  "other",
];

function generateBlockRules(domains) {
  const rules = [];
  let id = RULE_ID_START;

  for (const domain of domains) {
    rules.push({
      id: id++,
      priority: 1,
      action: {
        type: "redirect",
        redirect: {
          url:
            chrome.runtime.getURL("blocked.html") +
            "?domain=" +
            encodeURIComponent(domain),
        },
      },
      condition: {
        urlFilter: `||${domain}`,
        resourceTypes: ALL_RESOURCE_TYPES,
      },
    });
  }

  return rules;
}

function generateWhitelistRules(allowedDomains) {
  const rules = [];
  let id = RULE_ID_START;

  // Block everything by default
  rules.push({
    id: id++,
    priority: 1,
    action: {
      type: "redirect",
      redirect: {
        url: chrome.runtime.getURL("blocked.html") + "?domain=all",
      },
    },
    condition: {
      urlFilter: "*",
      resourceTypes: ALL_RESOURCE_TYPES,
      excludedInitiatorDomains: [chrome.runtime.id],
    },
  });

  // Allow specific domains (higher priority)
  for (const domain of allowedDomains) {
    rules.push({
      id: id++,
      priority: 2,
      action: { type: "allow" },
      condition: {
        urlFilter: `||${domain}`,
        resourceTypes: ALL_RESOURCE_TYPES,
      },
    });
  }

  // Always allow localhost for the dashboard
  ["127.0.0.1", "localhost"].forEach((host) => {
    rules.push({
      id: id++,
      priority: 2,
      action: { type: "allow" },
      condition: {
        urlFilter: `||${host}`,
        resourceTypes: ALL_RESOURCE_TYPES,
      },
    });
  });

  return rules;
}

// ── Core Blocking Logic ───────────────────────────────────────────────────────

async function clearBlockRules() {
  try {
    const existing = await getDynamicRules();
    if (existing.length > 0) {
      await updateDynamicRules(
        [],
        existing.map((r) => r.id),
      );
      log(`Cleared ${existing.length} block rules.`);
    }
  } catch (err) {
    log(`Failed to clear rules: ${err.message}`, "error");
  }
}

async function applyBlockRules(domains) {
  await clearBlockRules();
  if (domains.length === 0) {
    log("No domains to block.");
    return;
  }
  const rules = generateBlockRules(domains);
  await updateDynamicRules(rules);
  log(`Applied ${rules.length} block rules.`);
}

async function applyWhitelistRules(allowedDomains) {
  await clearBlockRules();
  const rules = generateWhitelistRules(allowedDomains);
  await updateDynamicRules(rules);
  log(
    `Applied whitelist rules: ${allowedDomains.length} allowed, rest blocked.`,
  );
}

// ── Session Management ────────────────────────────────────────────────────────

async function fetchSessionStatus() {
  try {
    const response = await fetchWithRetry(`${API}/api/status`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();
    // P3: Cache the status for content script requests
    cachedStatus = data;
    cacheTimestamp = Date.now();
    return data;
  } catch (error) {
    log(`Failed to fetch session status: ${error.message}`, "error");
    throw error;
  }
}

async function fetchSessionDomains() {
  try {
    const response = await fetchWithRetry(`${API}/api/session-domains`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    log(`Failed to fetch session domains: ${error.message}`, "error");
    throw error;
  }
}

async function syncBlockRules() {
  // P4: Guard against cascading syncs from overlapping alarms
  if (syncInProgress) return;
  syncInProgress = true;

  try {
    const status = await fetchSessionStatus();

    // Reset connection attempts on successful fetch
    connectionAttempts = 0;
    if (isRetrying) {
      isRetrying = false;
      chrome.alarms.clear("syncRules");
      chrome.alarms.create("syncRules", { periodInMinutes: 0.05 });
      log("Server reconnected — restored fast polling.");
    }

    // S3: Detect pomodoro phase transitions and broadcast to popup/content scripts
    const currentPhase =
      status.active && status.session_type === "pomodoro"
        ? status.pomo_phase
        : null;
    if (currentPhase !== lastPhase) {
      lastPhase = currentPhase;
      await saveState();
      // Broadcast to all extension pages (popup, blocked tabs)
      chrome.runtime
        .sendMessage({
          action: "phaseChanged",
          phase: currentPhase,
          active: status.active,
        })
        .catch(() => {
          // No receivers (popup closed) — safe to ignore
        });
      log(`Phase changed: ${currentPhase || "none"}`);
    }

    // During pomodoro break, clear block rules
    if (
      status.active &&
      status.session_type === "pomodoro" &&
      status.pomo_phase === "break"
    ) {
      if (lastActive) {
        await clearBlockRules();
        lastActive = false;
        lastMode = null;
        await saveState();
      }
      chrome.action.setBadgeText({ text: "BRK" });
      chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
      return;
    }

    if (status.active && status.mode === "blacklist") {
      if (!lastActive || lastMode !== "blacklist") {
        const sessionData = await fetchSessionDomains();
        const domains = sessionData.domains || [];
        await applyBlockRules(domains);
        await clearBrowserCache();
        lastActive = true;
        lastMode = "blacklist";
        await saveState();
      }
    } else if (status.active && status.mode === "whitelist") {
      const isRescue = status.session_type === "rescue";
      const modeKey = isRescue ? "rescue" : "whitelist";
      if (!lastActive || lastMode !== modeKey) {
        let allowed = [];
        if (!isRescue) {
          const sessionData = await fetchSessionDomains();
          allowed = sessionData.domains || [];
        }
        await applyWhitelistRules(allowed);
        await clearBrowserCache();
        lastActive = true;
        lastMode = modeKey;
        await saveState();
      }
    } else {
      // Idle — remove all rules
      if (lastActive) {
        await clearBlockRules();
        lastActive = false;
        lastMode = null;
        await saveState();
      }
    }

    // Update badge
    if (status.active) {
      chrome.action.setBadgeText({ text: "ON" });
      chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    } else {
      chrome.action.setBadgeText({ text: "" });
    }
  } catch (error) {
    connectionAttempts++;
    log(
      `Server unreachable (${connectionAttempts} attempts) — keeping existing rules.`,
      "warn",
    );

    if (connectionAttempts > 10 && !isRetrying) {
      isRetrying = true;
      log(
        "Connection attempts exceeded threshold. Reducing poll frequency.",
        "warn",
      );
      chrome.alarms.clear("syncRules");
      chrome.alarms.create("syncRules", { periodInMinutes: 1 });
    }
  } finally {
    syncInProgress = false;
  }
}

// ── Extension Lifecycle ───────────────────────────────────────────────────────

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "syncRules") {
    syncBlockRules();
  }
});

chrome.runtime.onStartup.addListener(() => {
  log("Extension started");
  chrome.alarms.create("syncRules", { periodInMinutes: 0.05 });
  loadState().then(() => syncBlockRules());
});

chrome.runtime.onInstalled.addListener((details) => {
  log(`Extension installed/updated: ${details.reason}`);
  chrome.storage.local.get(["analytics"], (result) => {
    if (!result.analytics) {
      chrome.storage.local.set({ analytics });
    } else {
      analytics = result.analytics;
    }
  });
  chrome.alarms.create("syncRules", { periodInMinutes: 0.05 });
  loadState().then(() => syncBlockRules());
});

// Also run immediately on service worker start (covers wakeup from suspension)
loadState().then(() => syncBlockRules());

// ── Message Handling ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "getAnalytics") {
    chrome.storage.local.get(["analytics"], (result) => {
      sendResponse(result.analytics || analytics);
    });
    return true;
  }

  if (message.action === "resetAnalytics") {
    analytics = {
      blockedRequests: 0,
      allowedRequests: 0,
      startTime: Date.now(),
    };
    chrome.storage.local.set({ analytics });
    sendResponse({ success: true });
    return true;
  }

  // P3: Serve cached status to reduce daemon requests from multiple blocked tabs
  if (message.action === "getTimeRemaining") {
    const now = Date.now();
    if (
      cachedStatus &&
      now - cacheTimestamp < CACHE_TTL &&
      cachedStatus.active
    ) {
      sendResponse({
        remaining: cachedStatus.remaining_seconds || 0,
        phase: cachedStatus.pomo_phase || null,
        phaseRemaining: cachedStatus.pomo_phase_remaining || null,
      });
    } else {
      fetch(`${API}/api/status`, { signal: AbortSignal.timeout(2000) })
        .then((res) => res.json())
        .then((data) => {
          cachedStatus = data;
          cacheTimestamp = Date.now();
          if (data.active) {
            sendResponse({
              remaining: data.remaining_seconds || 0,
              phase: data.pomo_phase || null,
              phaseRemaining: data.pomo_phase_remaining || null,
            });
          } else {
            sendResponse({ remaining: 0 });
          }
        })
        .catch(() => sendResponse({ remaining: 0 }));
    }
    return true;
  }

  // S3: Broadcast phase changes to popup
  if (message.action === "forceSync") {
    syncBlockRules();
    sendResponse({ ok: true });
    return true;
  }
});
