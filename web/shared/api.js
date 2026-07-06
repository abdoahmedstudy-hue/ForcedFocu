let apiToken = "";
const activeRequests = new Map();

async function loadApiToken() {
  if (window.apiToken) {
    apiToken = window.apiToken;
  }
}

export async function api(method, endpoint, body = null, baseUrl = "") {
  const url = baseUrl + endpoint;
  const headers = { "Content-Type": "application/json" };
  
  if (!apiToken) {
    await loadApiToken();
  }
  
  if (apiToken) headers["X-API-Token"] = apiToken;
  const opts = { method, headers, cache: "no-store" };
  if (body) opts.body = JSON.stringify(body);

  // Flow Reliability: Prevent GET request race conditions and overlap
  const requestKey = method + ":" + url;
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
    const res = await fetch(url, opts);
    // S4: Auto-refresh token on 401 (daemon restarted)
    if (res.status === 401) {
      await loadApiToken();
      if (apiToken) headers["X-API-Token"] = apiToken;
      const retryOpts = { 
        method, 
        headers,
        signal: AbortSignal.timeout(5000) // WB1: Prevent indefinite hang on retry
      };
      if (body) retryOpts.body = JSON.stringify(body);
      const retry = await fetch(url, retryOpts);
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
