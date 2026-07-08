export function escapeHtml(str) {
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

export function formatTime(totalSeconds) {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function extractDomain(input) {
  let d = input.trim().toLowerCase();
  if (!d) return "";

  try {
    if (d.includes("://")) {
      const url = new URL(d);
      d = url.hostname || url.pathname;
    } else {
      d = d.split("/")[0].split("?")[0].split("#")[0];
    }
  } catch (e) {
    d = d.split("/")[0].split("?")[0].split("#")[0];
  }

  // Strip port
  d = d.split(":")[0];

  // Strip www.
  if (d.startsWith("www.")) {
    d = d.substring(4);
  }

  // Strip wildcard characters
  d = d.replace(/^\*\.?/, "").replace(/\*$/, "");

  // Strict backend validation match
  if (d.length > 253) return "";
  if (/[\n\r\t \\/]/.test(d)) return "";
  if (!d.includes(".")) return "";
  if (d.startsWith(".") || d.startsWith("-") || d.endsWith(".") || d.endsWith("-")) return "";
  if (!/^[a-z0-9]([a-z0-9\-\.]*[a-z0-9])?$/.test(d)) return "";
  if (d.includes("..")) return "";

  return d;
}

let _toastTimeout = null;
export function showToast(toastEl, msg, duration = 3000) {
  if (!toastEl) return;
  if (_toastTimeout) clearTimeout(_toastTimeout);
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  toastEl.classList.add("show");
  _toastTimeout = setTimeout(() => {
    toastEl.classList.remove("show");
    // Wait for opacity transition before fully hiding
    setTimeout(() => toastEl.classList.add("hidden"), 300);
  }, duration);
}
