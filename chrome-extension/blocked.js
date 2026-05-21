// blocked.js — ForcedFocus Chrome Extension blocked page script
// Accurate, drift-free timer synced directly to the daemon's monotonic clock.
// Supports both session-based blocks and permanent blocks.

const API = "http://127.0.0.1:7070";
import { formatTime } from "./shared/utils.js";

// ── Domain Display ───────────────────────────────────────────────────────────
const params = new URLSearchParams(window.location.search);
const domain = params.get("domain") || "this site";
document.getElementById("blockedDomain").textContent = domain;
document.title = `Blocked: ${domain} — ForcedFocus`;

// ── Timer State ──────────────────────────────────────────────────────────────
let endTime = 0;           // Date.now() + remaining_ms at last sync
let totalDuration = 0;     // total session duration in seconds
let sessionType = null;    // "standard" | "pomodoro" | "rescue"
let pomoPhase = null;      // "focus" | "break"
let isSessionActive = false;
let isPermaBlocked = false;  // true if domain is in permanent blocklist
let permaHasPending = false; // true if a pending unblock exists
let permaEndTime = 0;       // Date.now() + pending unblock remaining
let tickRAF = null;         // requestAnimationFrame ID

let port = null;
let soundPlayed = false;

const badge = document.querySelector(".badge");
const messageEl = document.querySelector(".message");
const iconEl = document.querySelector(".icon");
const titleEl = document.querySelector("h1");

// ── Daemon Sync ──────────────────────────────────────────────────────────────

// ── Connection & State Sync ──────────────────────────────────────────────────

function log(message) {
  console.log(`[ForcedFocus][Blocked] ${message}`);
}

function requestSync() {
  chrome.runtime.sendMessage({ action: "forceSync" }).catch(() => {});
}

function playBlockedSound(settings) {
  if (soundPlayed) return;
  const file = settings?.settings?.sound_blocked;
  if (file) {
    soundPlayed = true;
    try {
      const audio = new Audio(`${API}/sounds/${encodeURIComponent(file)}`);
      audio.volume = 0.6;
      audio.play().catch(() => {});
    } catch (e) {
      console.warn("Could not play blocked sound:", e);
    }
  }
}

function handleStateUpdate(status, permaBlocklist, settings) {
  if (settings) {
    playBlockedSound(settings);
  }

  // Check permanent blocklist first
  const permaDomains = permaBlocklist?.domains || [];
  const pendingUnlocks = permaBlocklist?.pending_unlocks || {};

  // Check if the current domain (or its parent) is permanently blocked
  const domainLower = domain.toLowerCase();
  const isInPerma = permaDomains.some(d => {
    return domainLower === d || domainLower.endsWith("." + d);
  });

  if (isInPerma) {
    isPermaBlocked = true;

    // Check for pending unblock
    const matchedPerma = permaDomains.find(d =>
      domainLower === d || domainLower.endsWith("." + d)
    );
    const pending = matchedPerma ? pendingUnlocks[matchedPerma] : null;

    if (pending && pending.remaining_seconds > 0) {
      permaHasPending = true;
      permaEndTime = Date.now() + pending.remaining_seconds * 1000;
      if (!tickRAF) startTick();
    } else {
      permaHasPending = false;
      permaEndTime = 0;
      showPermaBlocked();
    }

    // If also session-active, perma takes visual priority (more permanent)
    return;
  }

  // Not permanently blocked — check session
  isPermaBlocked = false;

  if (status && status.active) {
    isSessionActive = true;
    sessionType = status.session_type || "standard";
    pomoPhase = status.pomo_phase || null;
    totalDuration = status.total_duration_seconds || 0;

    let remaining;
    if (sessionType === "pomodoro" && status.pomo_phase_remaining != null) {
      remaining = status.pomo_phase_remaining;
    } else {
      remaining = status.remaining_seconds || 0;
    }

    endTime = Date.now() + remaining * 1000;
    if (!tickRAF) startTick();
  } else {
    isSessionActive = false;
    endTime = 0;
    showEnded();
  }
}

// ── Smooth Local Countdown ───────────────────────────────────────────────────

let lastDisplayedSecond = -1;

function startTick() {
  function tick() {
    const now = Date.now();

    // Permanent block with pending unblock timer
    if (isPermaBlocked && permaHasPending) {
      const remMs = permaEndTime - now;
      if (remMs <= 0) {
        // Timer expired — re-sync
        lastDisplayedSecond = -1;
        requestSync();
        tickRAF = null;
        return;
      }
      const remSecs = Math.ceil(remMs / 1000);
      if (remSecs !== lastDisplayedSecond) {
        lastDisplayedSecond = remSecs;
        updatePermaDisplay(remSecs);
      }
      tickRAF = requestAnimationFrame(tick);
      return;
    }

    // Session-based timer
    const remMs = endTime - now;
    if (remMs <= 0) {
      if (badge) badge.textContent = "⚡ Syncing...";
      lastDisplayedSecond = -1;
      requestSync();
      tickRAF = null;
      return;
    }

    const remSecs = Math.ceil(remMs / 1000);
    if (remSecs !== lastDisplayedSecond) {
      lastDisplayedSecond = remSecs;
      updateSessionDisplay(remSecs);
    }

    tickRAF = requestAnimationFrame(tick);
  }

  tickRAF = requestAnimationFrame(tick);
}

// ── Display Functions ────────────────────────────────────────────────────────



function updateSessionDisplay(remSecs) {
  if (!badge) return;
  const timeStr = formatTime(remSecs);

  if (sessionType === "pomodoro" && pomoPhase) {
    const prefix = pomoPhase === "focus" ? "🍅" : "☕";
    badge.textContent = `${prefix} ${pomoPhase.toUpperCase()} — ${timeStr} remaining`;
  } else {
    badge.textContent = `⚡ ${timeStr} remaining`;
  }
}

function updatePermaDisplay(remSecs) {
  if (!badge) return;
  const timeStr = formatTime(remSecs);
  badge.textContent = `⏳ Unblock pending — ${timeStr} remaining`;
  badge.style.color = "#fbbf24";
  badge.style.background = "rgba(251, 191, 36, 0.15)";
  badge.style.boxShadow = "0 0 10px rgba(251, 191, 36, 0.1)";
}

function showPermaBlocked() {
  if (tickRAF) {
    cancelAnimationFrame(tickRAF);
    tickRAF = null;
  }

  // Update visual identity for permanent block
  if (iconEl) iconEl.textContent = "🔒";
  if (titleEl) {
    titleEl.textContent = "Permanently Blocked";
    titleEl.style.background = "linear-gradient(135deg, #dc2626, #b91c1c)";
    titleEl.style.webkitBackgroundClip = "text";
    titleEl.style.backgroundClip = "text";
  }
  if (messageEl) {
    messageEl.innerHTML =
      "This site is <strong>permanently blocked</strong> by ForcedFocus.<br />" +
      "Removal requires passphrase + 30-minute cooling period.";
  }
  if (badge) {
    badge.textContent = "🔒 Permanently Blocked";
    badge.style.color = "#f87171";
    badge.style.background = "rgba(239, 68, 68, 0.2)";
    badge.style.boxShadow = "0 0 15px rgba(239, 68, 68, 0.15)";
  }

  // Tint the container border red
  const container = document.querySelector(".container");
  if (container) {
    container.style.borderColor = "rgba(239, 68, 68, 0.15)";
  }
}

function showEnded() {
  if (tickRAF) {
    cancelAnimationFrame(tickRAF);
    tickRAF = null;
  }
  if (badge) {
    badge.textContent = "✅ Session ended — you can close this tab";
    badge.style.color = "#22c55e";
    badge.style.background = "rgba(34, 197, 94, 0.15)";
    badge.style.boxShadow = "0 0 10px rgba(34, 197, 94, 0.1)";
  }
}

// ── Init & Connection ────────────────────────────────────────────────────────

function connectToBackground() {
  port = chrome.runtime.connect({ name: "blocked-tab" });

  port.onMessage.addListener((msg) => {
    if (msg.action === "stateUpdated") {
      handleStateUpdate(msg.status, msg.permaBlocklist, msg.settings);
    }
  });

  port.onDisconnect.addListener(() => {
    log("Disconnected from background. Reconnecting...");
    port = null;
    // SW 5-Minute Rule: reconnection loop
    setTimeout(connectToBackground, 1000);
  });
}

// Establish port connection
connectToBackground();

// Query initial state via getBlockState runtime message
chrome.runtime.sendMessage({ action: "getBlockState" }, (response) => {
  if (chrome.runtime.lastError) {
    // Service Worker might be starting up, trigger a sync fallback
    requestSync();
    return;
  }
  if (response) {
    handleStateUpdate(response.status, response.permaBlocklist, response.settings);
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    requestSync();
  }
});
