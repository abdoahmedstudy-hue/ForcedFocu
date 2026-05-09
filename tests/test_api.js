async function test() {
  try {
    const res = await fetch("http://127.0.0.1:7070/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Token": require('fs').readFileSync('/etc/forcefocus/api_token', 'utf8').trim() },
      body: JSON.stringify({
        duration: 120,
        mode: "blacklist",
        session_type: "standard",
        groups: [],
        intent: "🎯 Focus Intent"
      })
    });
    console.log("Status:", res.status);
    console.log("Body:", await res.text());
  } catch (e) {
    console.error("Error:", e);
  }
}
test();
