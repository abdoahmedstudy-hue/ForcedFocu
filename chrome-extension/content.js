/**
 * ForcedFocus Content Script
 * Injects into web pages to provide additional functionality and
 * integration with the ForcedFocus ecosystem.
 * R7: Guarded against extension context invalidation.
 */

// Only run on pages that are being blocked by ForcedFocus
const urlParams = new URLSearchParams(window.location.search);
const blockedDomain = urlParams.get("domain");

if (blockedDomain) {
  // Add styling for blocked pages
  const style = document.createElement("style");
  style.textContent = `
    body.forcedfocus-blocked {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      margin: 0;
      padding: 20px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
    }

    .forcedfocus-container {
      max-width: 600px;
      padding: 2rem;
      background: rgba(30, 41, 59, 0.8);
      border-radius: 12px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
    }

    .forcedfocus-icon {
      font-size: 4rem;
      margin-bottom: 1rem;
    }

    .forcedfocus-title {
      font-size: 2rem;
      font-weight: 700;
      margin: 0 0 1rem 0;
      color: #f87171;
    }

    .forcedfocus-message {
      font-size: 1.1rem;
      line-height: 1.6;
      margin-bottom: 1.5rem;
    }

    .forcedfocus-domain {
      background: rgba(239, 68, 68, 0.1);
      color: #f87171;
      padding: 0.25rem 0.5rem;
      border-radius: 4px;
      font-family: monospace;
      font-size: 1rem;
    }

    .forcedfocus-timer {
      font-size: 1.5rem;
      font-weight: 600;
      color: #60a5fa;
      margin: 1rem 0;
    }

    .forcedfocus-footer {
      font-size: 0.9rem;
      color: #94a3b8;
      margin-top: 2rem;
    }

    .forcedfocus-button {
      background: #3b82f6;
      color: white;
      border: none;
      padding: 0.75rem 1.5rem;
      border-radius: 6px;
      font-size: 1rem;
      cursor: pointer;
      transition: background 0.2s;
      text-decoration: none;
      display: inline-block;
    }

    .forcedfocus-button:hover {
      background: #2563eb;
    }
  `;
  document.head.appendChild(style);

  // R2: Build blocked page with safe DOM construction — NO innerHTML with user data
  document.body.className = "forcedfocus-blocked";
  document.body.textContent = ""; // Clear safely

  const container = document.createElement("div");
  container.className = "forcedfocus-container";

  const icon = document.createElement("div");
  icon.className = "forcedfocus-icon";
  icon.textContent = "🚫";

  const title = document.createElement("h1");
  title.className = "forcedfocus-title";
  title.textContent = "Website Blocked";

  const message = document.createElement("p");
  message.className = "forcedfocus-message";
  message.appendChild(document.createTextNode("Access to "));
  const domainSpan = document.createElement("span");
  domainSpan.className = "forcedfocus-domain";
  domainSpan.textContent = blockedDomain; // R2: textContent — safe, no XSS
  message.appendChild(domainSpan);
  message.appendChild(
    document.createTextNode(" has been blocked by ForcedFocus."),
  );

  const timer = document.createElement("div");
  timer.className = "forcedfocus-timer";
  timer.id = "timer";
  timer.textContent = "Session ends in: calculating...";

  const footer = document.createElement("p");
  footer.className = "forcedfocus-footer";
  footer.textContent =
    "Use your focused time productively. Consider working on important tasks.";

  const closeBtn = document.createElement("a");
  closeBtn.href = "#";
  closeBtn.className = "forcedfocus-button";
  closeBtn.id = "closeTab";
  closeBtn.textContent = "Close This Tab";

  container.appendChild(icon);
  container.appendChild(title);
  container.appendChild(message);
  container.appendChild(timer);
  container.appendChild(footer);
  container.appendChild(closeBtn);
  document.body.appendChild(container);

  // Add close tab functionality
  closeBtn.addEventListener("click", (e) => {
    e.preventDefault();
    window.close();
  });

  // R7: Guard all chrome.runtime calls against extension context invalidation
  function isExtensionValid() {
    try {
      return !!(chrome.runtime && chrome.runtime.id);
    } catch {
      return false;
    }
  }

  // Fetch remaining time from the extension
  function updateTimer() {
    if (!isExtensionValid()) {
      clearInterval(timerPoll);
      const t = document.getElementById("timer");
      if (t) t.textContent = "Session active — stay focused!";
      return;
    }

    try {
      chrome.runtime.sendMessage({ action: "getTimeRemaining" }, (response) => {
        if (chrome.runtime.lastError) {
          // Service worker sleeping or extension reloaded
          const t = document.getElementById("timer");
          if (t) t.textContent = "Session active — stay focused!";
          return;
        }
        if (response && response.remaining > 0) {
          const t = document.getElementById("timer");
          if (t) {
            const h = Math.floor(response.remaining / 3600);
            const minutes = Math.floor((response.remaining % 3600) / 60);
            const seconds = response.remaining % 60;
            t.textContent = `Session ends in: ${h > 0 ? h + ":" : ""}${String(minutes).padStart(2, "0")}:${String(seconds).toString().padStart(2, "0")}`;
          }
        } else if (response && response.remaining === 0) {
          const t = document.getElementById("timer");
          if (t) t.textContent = "Session ended! You can close this tab.";
        }
      });
    } catch (e) {
      clearInterval(timerPoll);
    }
  }

  updateTimer();
  // R5/P3: Poll every 2s instead of 1s to reduce daemon load
  const timerPoll = setInterval(updateTimer, 2000);
}
