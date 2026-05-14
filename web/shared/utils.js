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
  // Strip protocol
  d = d.replace(/^https?:\/\//, "");
  // Strip path, query, hash
  d = d.split("/")[0].split("?")[0].split("#")[0];
  // Strip port
  d = d.split(":")[0];
  // Strip wildcard characters (e.g., *.example.com → example.com, example.com* → example.com)
  d = d.replace(/^\*\.?/, "").replace(/\*$/, "");
  return d;
}
