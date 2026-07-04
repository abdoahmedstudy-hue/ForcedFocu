/**
 * ForcedFocus Chrome Extension — Background Service Worker
 * Actively blocks blacklisted domains at the browser level using
 * declarativeNetRequest, preventing bypass via Chrome's Secure DNS.
 * Includes analytics, retry logic, adaptive polling, and state persistence.
 *
 * Redirect Architecture (R1):
 * DNR rules handle sub-resource blocking (block type) while webNavigation
 * listeners handle main_frame redirects to blocked.html. This two-layer
 * approach ensures redirects work even when /etc/hosts blocks the domain
 * before DNR can fire (causing ERR_CONNECTION_REFUSED).
 */

const API = "http://127.0.0.1:7070";
const POLL_INTERVAL = 3000;
const RULE_ID_START = 1000;
const MAX_RETRY_ATTEMPTS = 3;
const RETRY_DELAY = 2000;
const FALLBACK_DYNAMIC_RULE_LIMIT = 5000;

// State management — persisted via chrome.storage.session to survive SW suspension
let lastActive = false;
let lastMode = null;
let lastPhase = null; // S3: Track pomodoro phase for change broadcasts
let lastRulesSignature = "";
let connectionAttempts = 0;
let isRetrying = false;
let syncInProgress = false; // P4: Guard against cascading syncs
let apiToken = "";
class RuleCapacityError extends Error {
  constructor(message) {
    super(message);
    this.name = "RuleCapacityError";
  }
}

function getDynamicRuleLimit() {
  return (
    chrome.declarativeNetRequest.MAX_NUMBER_OF_DYNAMIC_RULES ||
    chrome.declarativeNetRequest.MAX_NUMBER_OF_DYNAMIC_AND_SESSION_RULES ||
    FALLBACK_DYNAMIC_RULE_LIMIT
  );
}

function assertDynamicRuleCapacity(rules, context) {
  const limit = getDynamicRuleLimit();
  if (rules.length <= limit) return;
  throw new RuleCapacityError(
    `${context} would require ${rules.length} Chrome DNR rules, exceeding the limit of ${limit}. Reduce the active domain list or split the session.`,
  );
}

function surfaceRuleCapacityError(error) {
  log(error.message, "error");
  chrome.action.setBadgeText({ text: "ERR" });
  chrome.action.setBadgeBackgroundColor({ color: "#b91c1c" });
  chrome.notifications.create("forcedfocus-rule-capacity", {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "ForcedFocus rule limit reached",
    message: error.message,
    priority: 1,
  });
}

async function loadApiToken() {
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
    console.error("[ForcedFocus] Background token load failed:", e);
  }
}

// R1: In-memory set of currently blocked domains for O(1) webNavigation lookups
let blockedDomainsSet = new Set();
// R1: Current blocking mode — "blacklist", "whitelist", "rescue", or null
let currentBlockMode = null;
// Permanent blocklist — always enforced, independent of session
let permaBlockedSet = new Set();
let lastPermaHash = ""; // Hash of perma domains to detect changes

// Cache variables
let cachedPermaData = null;
let cachedSettings = null;

// Track active blocked tab ports
const activePorts = new Set();

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
      "lastRulesSignature",
      "blockedDomains",
      "currentBlockMode",
      "permaDomains",
      "cachedStatus",
      "cachedPermaData",
      "cachedSettings",
    ]);
    lastActive = result.lastActive || false;
    lastMode = result.lastMode || null;
    lastPhase = result.lastPhase || null;
    lastRulesSignature = result.lastRulesSignature || "";
    // R1: Restore blocked domains set from storage (survives SW suspension)
    if (result.blockedDomains && Array.isArray(result.blockedDomains)) {
      blockedDomainsSet = new Set(result.blockedDomains);
    }
    currentBlockMode = result.currentBlockMode || null;
    if (result.permaDomains && Array.isArray(result.permaDomains)) {
      permaBlockedSet = new Set(result.permaDomains);
    }
    cachedStatus = result.cachedStatus || null;
    cachedPermaData = result.cachedPermaData || null;
    cachedSettings = result.cachedSettings || null;
  } catch (e) {
    // storage.session may not be available in older Chrome versions
    console.warn("[ForcedFocus] Could not load session state:", e);
  }
}

async function saveState() {
  try {
    await chrome.storage.session.set({
      lastActive,
      lastMode,
      lastPhase,
      lastRulesSignature,
      // R1: Persist blocked domains (capped at 5000 to avoid storage limits)
      blockedDomains: [...blockedDomainsSet].slice(0, 5000),
      currentBlockMode,
      permaDomains: [...permaBlockedSet].slice(0, 5000),
      cachedStatus,
      cachedPermaData,
      cachedSettings,
    });
  } catch (e) {
    // Non-critical — state will just be re-synced on next poll
  }
}

// Define state loaded promise
const stateLoadedPromise = loadState();

// ── Utility Functions ─────────────────────────────────────────────────────────

function log(message, level = "info") {
  const timestamp = new Date().toISOString();
  console.log(`[ForcedFocus][${timestamp}][${level.toUpperCase()}] ${message}`);
}

function normalizeDomains(domains = []) {
  return [...new Set(domains.map((d) => String(d).trim().toLowerCase()).filter(Boolean))].sort();
}

function buildRulesSignature(modeKey, sessionDomains = []) {
  const sessionPart = normalizeDomains(sessionDomains).join(",");
  const permaPart = normalizeDomains([...permaBlockedSet]).join(",");
  return `${modeKey}|session:${sessionPart}|perma:${permaPart}`;
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
  // B2: Safety net — should be unreachable, but guards against silent undefined return
  throw new Error(`fetchWithRetry: All ${maxRetries} retries exhausted for ${url}`);
}

// ── Domain Matching (R1) ──────────────────────────────────────────────────────

/**
 * Extract the hostname from a URL string.
 * Returns lowercase hostname or null if parsing fails.
 */
function extractHostname(urlString) {
  try {
    const url = new URL(urlString);
    return url.hostname.toLowerCase();
  } catch {
    return null;
  }
}

/**
 * Check if a hostname is blocked by comparing against the blocked domains set.
 * Handles subdomain matching: if "reddit.com" is blocked, "www.reddit.com" matches.
 */
function isHostnameBlocked(hostname) {
  if (!hostname || blockedDomainsSet.size === 0) return false;

  // Direct match
  if (blockedDomainsSet.has(hostname)) return true;

  // Walk up the domain hierarchy for subdomain matching
  // e.g., "old.reddit.com" → check "reddit.com" → check "com"
  const parts = hostname.split(".");
  for (let i = 1; i < parts.length - 1; i++) {
    const parent = parts.slice(i).join(".");
    if (blockedDomainsSet.has(parent)) return true;
  }

  return false;
}

/**
 * Check if a URL should be blocked.
 * Excludes extension URLs, localhost, and chrome:// pages.
 */
function shouldBlockUrl(urlString) {
  if (!urlString) return false;

  // Never block extension pages, chrome internals, or localhost
  if (
    urlString.startsWith("chrome") ||
    urlString.startsWith("about:") ||
    urlString.startsWith("chrome-extension://") ||
    urlString.startsWith("http://127.0.0.1") ||
    urlString.startsWith("http://localhost")
  ) {
    return false;
  }

  const hostname = extractHostname(urlString);
  if (!hostname) return false;

  // Always block permanently blocked domains (session-independent)
  if (isHostnamePermaBlocked(hostname)) return true;

  if (currentBlockMode === "blacklist") {
    // Blacklist: block if domain is in the set
    return isHostnameBlocked(hostname);
  } else if (currentBlockMode === "whitelist" || currentBlockMode === "rescue" || currentBlockMode === "ban") {
    // Whitelist/Rescue/Ban: block if domain is NOT in the allowed set
    // For rescue mode, blockedDomainsSet is empty (nothing allowed)
    if (hostname === "127.0.0.1" || hostname === "localhost") return false;
    return !isHostnameBlocked(hostname);
  }

  return false;
}

/**
 * Check if a hostname is permanently blocked.
 */
function isHostnamePermaBlocked(hostname) {
  if (!hostname || permaBlockedSet.size === 0) return false;
  if (permaBlockedSet.has(hostname)) return true;
  const parts = hostname.split(".");
  for (let i = 1; i < parts.length - 1; i++) {
    const parent = parts.slice(i).join(".");
    if (permaBlockedSet.has(parent)) return true;
  }
  return false;
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

// R1: Sub-resource types — these get "block" action (redirect doesn't work for these)
const SUB_RESOURCE_TYPES = [
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

// R1: Main frame type — gets "redirect" action to blocked.html
const MAIN_FRAME_TYPES = ["main_frame"];

function generateBlockRules(domains, startId = RULE_ID_START) {
  const rules = [];
  let id = startId;

  for (const domain of domains) {
    // R1: Main frame navigations → redirect to blocked.html
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
        resourceTypes: MAIN_FRAME_TYPES,
      },
    });

    // R1: Sub-resources → block silently (redirect doesn't work for these in MV3)
    rules.push({
      id: id++,
      priority: 1,
      action: { type: "block" },
      condition: {
        urlFilter: `||${domain}`,
        resourceTypes: SUB_RESOURCE_TYPES,
      },
    });
  }

  return { rules, nextId: id };
}

function generateWhitelistRules(allowedDomains) {
  const rules = [];
  let id = RULE_ID_START;

  // R1: Block all main_frame navigations by default → redirect to blocked.html
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
      resourceTypes: MAIN_FRAME_TYPES,
      excludedInitiatorDomains: [chrome.runtime.id],
    },
  });

  // R1: Block all sub-resources by default → silent block
  rules.push({
    id: id++,
    priority: 1,
    action: { type: "block" },
    condition: {
      urlFilter: "*",
      resourceTypes: SUB_RESOURCE_TYPES,
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
        resourceTypes: [...MAIN_FRAME_TYPES, ...SUB_RESOURCE_TYPES],
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
        resourceTypes: [...MAIN_FRAME_TYPES, ...SUB_RESOURCE_TYPES],
      },
    });
  });

  // Permanent blocks must win even if a domain is also in the whitelist.
  for (const domain of normalizeDomains([...permaBlockedSet])) {
    rules.push({
      id: id++,
      priority: 3,
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
        resourceTypes: MAIN_FRAME_TYPES,
      },
    });
    rules.push({
      id: id++,
      priority: 3,
      action: { type: "block" },
      condition: {
        urlFilter: `||${domain}`,
        resourceTypes: SUB_RESOURCE_TYPES,
      },
    });
  }

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
  // Merge session domains with permanent blocklist
  const allDomains = normalizeDomains([...domains, ...permaBlockedSet]);
  if (allDomains.length === 0) {
    await clearBlockRules();
    log("No domains to block.");
    return;
  }
  const { rules } = generateBlockRules(allDomains);
  assertDynamicRuleCapacity(rules, "Blacklist session");
  await clearBlockRules();
  await updateDynamicRules(rules);
  // R1: Update in-memory blocked domains set for webNavigation matching
  blockedDomainsSet = new Set(normalizeDomains(domains));
  currentBlockMode = "blacklist";
  log(`Applied ${rules.length} block rules for ${allDomains.length} domains (${permaBlockedSet.size} permanent).`);
}

async function applyWhitelistRules(allowedDomains) {
  const rules = generateWhitelistRules(normalizeDomains(allowedDomains));
  assertDynamicRuleCapacity(rules, "Whitelist session");
  await clearBlockRules();
  await updateDynamicRules(rules);
  // R1: For whitelist, the set contains ALLOWED domains
  blockedDomainsSet = new Set(normalizeDomains(allowedDomains));
  currentBlockMode = "whitelist";
  log(
    `Applied whitelist rules: ${normalizeDomains(allowedDomains).length} allowed, rest blocked.`,
  );
}

// ── Permanent Blocklist Sync ──────────────────────────────────────────────────

async function syncPermaBlocklist() {
  try {
    if (!apiToken) {
      await loadApiToken();
    }
    const headers = {};
    if (apiToken) headers["X-API-Token"] = apiToken;
    let response = await fetch(`${API}/api/perma-blocklist`, {
      headers,
      signal: AbortSignal.timeout(3000),
    });
    if (response.status === 401) {
      await loadApiToken();
      const newHeaders = {};
      if (apiToken) newHeaders["X-API-Token"] = apiToken;
      response = await fetch(`${API}/api/perma-blocklist`, {
        headers: newHeaders,
        signal: AbortSignal.timeout(3000),
      });
    }
    if (!response.ok) return;
    const data = await response.json();
    
    // Cache the full payload containing domains and pending_unlocks
    cachedPermaData = data;
    await saveState();

    const domains = normalizeDomains(data.domains || []);

    // Quick hash check to avoid unnecessary rule rebuilds
    const hash = domains.join(",");
    if (hash === lastPermaHash) return;
    lastPermaHash = hash;

    const oldSize = permaBlockedSet.size;
    permaBlockedSet = new Set(domains);
    await saveState();

    log(`Permanent blocklist synced: ${permaBlockedSet.size} domains (was ${oldSize}).`);

    // If no session is active, apply/update perma rules directly
    if (!lastActive) {
      let rules = [];
      if (permaBlockedSet.size > 0) {
        ({ rules } = generateBlockRules([...permaBlockedSet]));
        assertDynamicRuleCapacity(rules, "Permanent blocklist");
      }
      await clearBlockRules();
      if (permaBlockedSet.size > 0) {
        await updateDynamicRules(rules);
        lastRulesSignature = buildRulesSignature("idle", []);
        log(`Applied ${rules.length} permanent block rules (no active session).`);
      } else {
        lastRulesSignature = buildRulesSignature("idle", []);
      }
      await saveState();
    }
    // If a session IS active, the rules will be merged on next applyBlockRules call
  } catch (e) {
    if (e.name === "RuleCapacityError") {
      surfaceRuleCapacityError(e);
    }
    // Non-critical — will retry on next sync cycle
  }
}

async function syncSettings() {
  try {
    if (!apiToken) {
      await loadApiToken();
    }
    const headers = {};
    if (apiToken) headers["X-API-Token"] = apiToken;
    let response = await fetch(`${API}/api/settings`, {
      headers,
      signal: AbortSignal.timeout(3000),
    });
    if (response.status === 401) {
      await loadApiToken();
      const newHeaders = {};
      if (apiToken) newHeaders["X-API-Token"] = apiToken;
      response = await fetch(`${API}/api/settings`, {
        headers: newHeaders,
        signal: AbortSignal.timeout(3000),
      });
    }
    if (!response.ok) return;
    const data = await response.json();
    cachedSettings = data;
    await saveState();
    log("Settings synced.");
  } catch (e) {
    // Non-critical
  }
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

async function syncBlockRules(status = null) {
  // P4: Guard against cascading syncs from overlapping alarms
  if (syncInProgress) return;
  syncInProgress = true;

  try {
    if (!status) {
      status = await fetchSessionStatus();
    } else {
      cachedStatus = status;
      cacheTimestamp = Date.now();
    }

    // P1: Sync permanent blocklist and settings in parallel (independent operations)
    await Promise.allSettled([syncPermaBlocklist(), syncSettings()]);

    // Reset connection attempts on successful fetch
    connectionAttempts = 0;
    if (isRetrying) {
      isRetrying = false;
      chrome.alarms.clear("syncRules");
      chrome.alarms.create("syncRules", { periodInMinutes: 1 });
      log("Server reconnected — restored background polling.");
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
      const breakSignature = buildRulesSignature("break", []);
      if (lastRulesSignature !== breakSignature || lastActive) {
        let permanentRules = [];
        if (permaBlockedSet.size > 0) {
          ({ rules: permanentRules } = generateBlockRules([...permaBlockedSet]));
          assertDynamicRuleCapacity(permanentRules, "Pomodoro break permanent blocklist");
        }
        await clearBlockRules();
        blockedDomainsSet.clear();
        currentBlockMode = null;
        if (permaBlockedSet.size > 0) {
          await updateDynamicRules(permanentRules);
          log(`Pomodoro break — kept ${permanentRules.length} permanent block rules.`);
        }
        lastActive = false;
        lastMode = null;
        lastRulesSignature = breakSignature;
        await saveState();
      }
      chrome.action.setBadgeText({ text: "BRK" });
      chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
      return;
    }

    if (status.active && status.mode === "blacklist") {
      const sessionData = await fetchSessionDomains();
      const domains = normalizeDomains(sessionData.domains || []);
      const nextSignature = buildRulesSignature("blacklist", domains);
      if (!lastActive || lastMode !== "blacklist" || lastRulesSignature !== nextSignature) {
        await applyBlockRules(domains);
        await clearBrowserCache();
        lastActive = true;
        lastMode = "blacklist";
        lastRulesSignature = nextSignature;
        await saveState();
      }
    } else if (status.active && (status.mode === "whitelist" || status.mode === "ban")) {
      const isRescue = status.session_type === "rescue";
      const isBan = status.mode === "ban";
      const modeKey = isRescue ? "rescue" : isBan ? "ban" : "whitelist";
      let allowed = [];
      if (!isRescue && !isBan) {
        const sessionData = await fetchSessionDomains();
        allowed = normalizeDomains(sessionData.domains || []);
      }
      const nextSignature = buildRulesSignature(modeKey, allowed);
      if (!lastActive || lastMode !== modeKey || lastRulesSignature !== nextSignature) {
        await applyWhitelistRules(allowed);
        currentBlockMode = modeKey;
        await clearBrowserCache();
        lastActive = true;
        lastMode = modeKey;
        lastRulesSignature = nextSignature;
        await saveState();
      }
    } else {
      // Idle — remove session rules but keep permanent blocks
      const idleSignature = buildRulesSignature("idle", []);
      if (lastActive || lastRulesSignature !== idleSignature) {
        let permanentRules = [];
        if (permaBlockedSet.size > 0) {
          ({ rules: permanentRules } = generateBlockRules([...permaBlockedSet]));
          assertDynamicRuleCapacity(permanentRules, "Idle permanent blocklist");
        }
        await clearBlockRules();
        blockedDomainsSet.clear();
        currentBlockMode = null;
        lastActive = false;
        lastMode = null;
        // Re-apply permanent block rules if any exist
        if (permaBlockedSet.size > 0) {
          await updateDynamicRules(permanentRules);
          log(`Session ended — re-applied ${permanentRules.length} permanent block rules.`);
        }
        lastRulesSignature = idleSignature;
        await saveState();
      }
    }

    // Update badge
    if (status.active) {
      chrome.action.setBadgeText({ text: "ON" });
      chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    } else if (permaBlockedSet.size > 0) {
      chrome.action.setBadgeText({ text: "🔒" });
      chrome.action.setBadgeBackgroundColor({ color: "#991b1b" });
    } else {
      chrome.action.setBadgeText({ text: "" });
    }

    // Broadcast state to active blocked tab ports
    broadcastToBlockedTabs();
  } catch (error) {
    if (error.name === "RuleCapacityError") {
      surfaceRuleCapacityError(error);
      return;
    }
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
      chrome.alarms.create("syncRules", { periodInMinutes: 5 }); // B1: Actually reduce frequency (was 1, same as normal)
    }
  } finally {
    syncInProgress = false;
  }
}

// ── WebNavigation Redirect (R1) ───────────────────────────────────────────────
// Two-layer redirect system that catches cases where /etc/hosts blocks the
// domain before DNR rules can fire (causing ERR_CONNECTION_REFUSED).

// Track recent notifications to debounce (prevent spam from rapid navigations)
const _notifiedDomains = new Map();
const NOTIF_DEBOUNCE_MS = 3000;
const NOTIF_DOMAINS_MAX = 100; // P2: Cap to prevent unbounded growth

/** P2: Purge stale entries from _notifiedDomains to prevent memory leak. */
function cleanupNotifiedDomains() {
  const now = Date.now();
  for (const [domain, timestamp] of _notifiedDomains) {
    if (now - timestamp > NOTIF_DEBOUNCE_MS * 10) {
      _notifiedDomains.delete(domain);
    }
  }
  // Hard cap: if still over limit, remove oldest entries
  if (_notifiedDomains.size > NOTIF_DOMAINS_MAX) {
    const entries = [..._notifiedDomains.entries()].sort((a, b) => a[1] - b[1]);
    const excess = entries.length - NOTIF_DOMAINS_MAX;
    for (let i = 0; i < excess; i++) {
      _notifiedDomains.delete(entries[i][0]);
    }
  }
}

chrome.webNavigation.onBeforeNavigate.addListener(async (details) => {
  // Only intercept top-level navigations (not iframes, etc.)
  if (details.frameId !== 0) return;

  await stateLoadedPromise;

  const now = Date.now();
  if (shouldBlockUrl(details.url)) {
    // If the cache is expired, verify current status with daemon immediately to prevent SW lag
    if (now - cacheTimestamp > CACHE_TTL) {
      try {
        const status = await fetchSessionStatus();
        // If daemon is actually idle, sync and skip block redirect
        if (!status.active && permaBlockedSet.size === 0) {
          await syncBlockRules(status);
          return;
        }
      } catch (e) {
        // Ignore network errors and fallback to blocking
      }
    }

    const hostname = extractHostname(details.url);
    const blockedUrl =
      chrome.runtime.getURL("blocked.html") +
      "?domain=" +
      encodeURIComponent(hostname || "this site");

    // Record for analytics
    if (hostname) recordBlockedRequest(hostname);

    chrome.tabs.update(details.tabId, { url: blockedUrl });
    log(`[R1] Pre-navigation redirect: ${hostname} → blocked.html`);

    // Chrome notification (debounced per domain)
    const nowNotif = Date.now();
    const lastNotif = _notifiedDomains.get(hostname) || 0;
    if (nowNotif - lastNotif > NOTIF_DEBOUNCE_MS) {
      cleanupNotifiedDomains(); // P2: Prevent unbounded growth
      _notifiedDomains.set(hostname, nowNotif);
      chrome.notifications.create(`blocked-${hostname}`, {
        type: "basic",
        iconUrl: "icons/icon128.png",
        title: "Site Blocked",
        message: `${hostname} is blocked by ForcedFocus. Stay focused!`,
        priority: 0,
      });
    }
  }
});

/**
 * Layer 2: Catch connection errors from /etc/hosts blocking.
 * When /etc/hosts resolves a domain to 127.0.0.1, Chrome shows
 * ERR_CONNECTION_REFUSED. This listener catches that error and
 * redirects to blocked.html as a fallback.
 */
chrome.webNavigation.onErrorOccurred.addListener(async (details) => {
  // Only handle top-level navigation errors
  if (details.frameId !== 0) return;

  // Only handle connection-related errors (from /etc/hosts blocking)
  const blockErrors = [
    "net::ERR_CONNECTION_REFUSED",
    "net::ERR_CONNECTION_RESET",
    "net::ERR_CONNECTION_TIMED_OUT",
    "net::ERR_NAME_NOT_RESOLVED",
    "net::ERR_ADDRESS_UNREACHABLE",
    "net::ERR_CONNECTION_CLOSED",
    "net::ERR_EMPTY_RESPONSE",
  ];

  if (!blockErrors.includes(details.error)) return;

  await stateLoadedPromise;

  const now = Date.now();
  // Check if this URL belongs to a blocked domain
  if (shouldBlockUrl(details.url)) {
    // Verify status immediately to prevent redirecting after the session ends
    if (now - cacheTimestamp > CACHE_TTL) {
      try {
        const status = await fetchSessionStatus();
        if (!status.active && permaBlockedSet.size === 0) {
          await syncBlockRules(status);
          return;
        }
      } catch (e) {}
    }

    const hostname = extractHostname(details.url);
    const blockedUrl =
      chrome.runtime.getURL("blocked.html") +
      "?domain=" +
      encodeURIComponent(hostname || "this site");

    chrome.tabs.update(details.tabId, { url: blockedUrl });
    log(
      `[R1] Error-fallback redirect: ${hostname} (${details.error}) → blocked.html`,
    );
  }
});

// ── Extension Lifecycle & IPC ──────────────────────────────────────────────────

let eventSource = null;
let sseReconnectTimer = null;

function scheduleSSEReconnect() {
  if (sseReconnectTimer) return;
  sseReconnectTimer = setTimeout(() => {
    sseReconnectTimer = null;
    connectSSE();
  }, 5000);
}

function connectSSE() {
  if (eventSource && (eventSource.readyState === 0 || eventSource.readyState === 1)) {
    return;
  }
  if (sseReconnectTimer) {
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = null;
  }
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`${API}/api/stream`);
  
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      syncBlockRules(data);
      // Broadcast to popup so it can refresh its UI immediately
      chrome.runtime.sendMessage({ action: "stateUpdated", state: data }).catch(() => {});
    } catch (err) {
      log(`SSE Parse Error: ${err.message}`, "error");
    }
  };
  
  eventSource.onerror = () => {
    log("SSE connection lost. Reconnecting in 5s...", "warning");
    eventSource.close();
    eventSource = null;
    scheduleSSEReconnect();
  };
}

function broadcastToBlockedTabs() {
  const payload = {
    action: "stateUpdated",
    status: cachedStatus,
    permaBlocklist: cachedPermaData,
    settings: cachedSettings,
  };
  log(`Broadcasting state to ${activePorts.size} active blocked tab ports.`);
  for (const port of activePorts) {
    try {
      port.postMessage(payload);
    } catch (e) {
      log(`Failed to post message to port: ${e.message}`, "error");
      activePorts.delete(port);
    }
  }
}

function ensureSyncAlarm() {
  chrome.alarms.create("syncRules", { periodInMinutes: 1 });
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "syncRules") {
    // Alarms are the guaranteed MV3 sync path; SSE is only best-effort.
    syncBlockRules();
  }
});

chrome.runtime.onStartup.addListener(() => {
  log("Extension started");
  ensureSyncAlarm();
  connectSSE();
  stateLoadedPromise.then(() => syncBlockRules());
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
  ensureSyncAlarm();
  connectSSE();
  stateLoadedPromise.then(() => syncBlockRules());
});

// Also run immediately on service worker start (covers wakeup from suspension)
ensureSyncAlarm();
connectSSE();
stateLoadedPromise.then(() => syncBlockRules());

// ── Connection Management ──────────────────────────────────────────────────────

chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "blocked-tab") {
    activePorts.add(port);
    log(`Blocked tab connected. Total active ports: ${activePorts.size}`);

    // Push initial state immediately inside onConnect (Push on Connect)
    if (cachedStatus || cachedPermaData || cachedSettings) {
      try {
        port.postMessage({
          action: "stateUpdated",
          status: cachedStatus,
          permaBlocklist: cachedPermaData,
          settings: cachedSettings,
        });
      } catch (e) {
        log(`Failed to send initial state to port: ${e.message}`, "error");
        activePorts.delete(port);
      }
    } else {
      syncBlockRules().then(() => {
        try {
          port.postMessage({
            action: "stateUpdated",
            status: cachedStatus,
            permaBlocklist: cachedPermaData,
            settings: cachedSettings,
          });
        } catch (e) {
          activePorts.delete(port);
        }
      });
    }

    port.onDisconnect.addListener(() => {
      activePorts.delete(port);
      log(`Blocked tab disconnected. Total active ports: ${activePorts.size}`);
    });
  }
});

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

  if (message.action === "getBlockState") {
    stateLoadedPromise.then(async () => {
      if (!cachedStatus) {
        try {
          await fetchSessionStatus();
        } catch (e) {}
      }
      if (!cachedPermaData) {
        try {
          await syncPermaBlocklist();
        } catch (e) {}
      }
      if (!cachedSettings) {
        try {
          await syncSettings();
        } catch (e) {}
      }
      sendResponse({
        status: cachedStatus,
        permaBlocklist: cachedPermaData,
        settings: cachedSettings,
      });
    });
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
