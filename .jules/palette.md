## 2026-05-09 - [Empty State Micro-UX]
**Learning:** Found that dynamic lists (like the Whitelist/Blacklist domain displays) lacked empty states, leaving a confusing empty gap when users remove all items. Blank spaces are often misinterpreted as bugs rather than an "empty" state.
**Action:** Added an explicit, styled empty state placeholder ("No domains added yet.") to `renderDomainList` in `app.js` with dashed borders and italicized muted text to convey absence without looking broken. I'll make sure to always render empty states for any list UI in the future.
