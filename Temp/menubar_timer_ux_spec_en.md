# macOS Menubar Timer UX Specification - ForcedFocus

This document establishes the logical and architectural design guidelines for the countdown timer feature in the macOS Menubar. All decisions are optimized to align with the core philosophy of ForcedFocus: providing a high-integrity, low-friction, and visually calm command center.

---

### 1. Psychological Impact & Visual Calm
* **Core Question:** Should the timer display seconds or only minutes during active focus to mitigate anxiety?
* **Product Decision:** The menubar item will display **minutes only** (e.g., `24m`) and completely hide the seconds. This eliminates the counterproductive habit of "clock-watching" and protects the user's mental focus from constant, rapid motion in their peripheral vision.

### 2. Space Management in the macOS Menubar
* **Core Question:** What is the most space-efficient format for displaying long sessions (hours and minutes) without overcrowding the menubar?
* **Product Decision:** Sessions will use the compact notation `2h 30m`. This provides clear, universally understood telemetry while ensuring a stable horizontal layout footprint that prevents neighboring system status icons from shifting or vibrating.

### 3. Glanceable Mode Differentiation
* **Core Question:** How does a user quickly differentiate between an active focus block, a pomodoro break, or an unbreakable rescue session?
* **Product Decision:** Status categorization will be driven by **monochrome (black and white) icon indicators** adjacent to the timer. Brightly colored emojis or neon badges are banned to ensure the app looks like a native, professional utility integrated into macOS, rather than a playful distraction.

### 4. Scheduled Blocks & Prayer Time Countdowns
* **Core Question:** How should the menubar prepare the user for upcoming routines or recurring blocks?
* **Product Decision:** The countdown will explicitly appear in the menubar exactly **5 minutes** prior to a scheduled session or prayer window. It will be accompanied by a downward trend arrow `⇣`, offering a silent, high-integrity psychological cue to wrap up current tasks without inducing premature context-switching.

### 5. Flexibility vs. Rigid Enforcement
* **Core Question:** Should the menubar timer display be optional via a settings toggle, or strictly mandatory?
* **Product Decision:** The visibility of the timer is **mandatory for all users**. In accordance with the product's foundational principles, eliminating unnecessary configuration toggles prevents users from procrastinating through customization and ensures consistent product integrity.

### 6. High-Urgency Behavior in the Final Minute
* **Core Question:** How should the visual rhythm shift when a focus session is about to expire?
* **Product Decision:** When the timer enters the final 60 seconds of a session, the display will automatically swap from minutes to **seconds** (e.g., `59s` down to `0s`). This subtle acceleration creates a "sprint finish" effect, motivating the user to complete their immediate train of thought. 
* *Note: This requires a monospaced/tabular numerals font configuration to avoid layout jittering as numbers change.*

### 7. Immediate Transition at Session Expiry (0s)
* **Core Question:** What exact visual and state transitions occur the split-second the timer hits zero?
* **Product Decision:** * The menubar text will instantly transform to read `Done` for exactly **2 seconds**, providing immediate cognitive closure and a sense of accomplishment.
  * **In Pomodoro Mode:** Immediately following the 2-second closure window, the system daemon will automatically advance and trigger the Break phase countdown, eliminating any manual intervention gaps and maintaining real-time client-daemon state synchronization.
