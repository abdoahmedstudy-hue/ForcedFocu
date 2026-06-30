# ForcedFocus Chrome Extension Permissions

ForcedFocus uses the smallest practical Manifest V3 permission set for local macOS blocking enforcement.

| Permission | Reason |
|---|---|
| `alarms` | Wakes the service worker for the guaranteed one-minute sync path when SSE is suspended. |
| `declarativeNetRequest` | Applies browser-level block and redirect rules without content-script interception. |
| `declarativeNetRequestFeedback` | Allows release/debug inspection of applied dynamic rules during QA. |
| `browsingData` | Clears cache and service workers after rule changes so blocked sites cannot continue from stale assets. |
| `notifications` | Shows a debounced browser notification when a blocked top-level navigation is intercepted. |
| `storage` | Persists service-worker session state, cached daemon state, and local analytics across suspension. |
| `webNavigation` | Catches top-level navigations and connection-error fallbacks when system hosts rules fire before DNR redirects. |
| `tabs` | Redirects the active tab to `blocked.html` for top-level blocked navigations. |
| `http://127.0.0.1:7070/*` | Reads the local ForcedFocus daemon API. |
| `http://localhost:7070/*` | Supports local daemon access when Chrome resolves the dashboard through `localhost`. |

No remote host permissions are requested.
