# ForcedFocus Unix Socket API Reference 🔌

The system daemon listens on a local Unix Domain Socket at `/var/run/forcefocus.sock`. The CLI connects directly to it.

---

## ⚠️ Socket Constraints

*   **Permissions**: Read and write access to `/var/run/forcefocus.sock` is limited to system administrator permissions (sudo/root) or standard desktop users allowed via daemon configuration.
*   **Buffer Limit**: The socket listener enforces a strict **1MB payload limit** (`MAX_MSG_SIZE = 1048576` bytes). Payloads exceeding this size (such as file uploads) will be rejected with `{"status": "error", "message": "Message too large."}`. File uploading must go through the HTTP REST API.

---

## 🎛️ API JSON Commands

### 1. status
Retrieves the current daemon session state.
*   **Request JSON**:
    ```json
    {
      "action": "status"
    }
    ```
*   **Response JSON (No Active Session)**:
    ```json
    {
      "status": "ok",
      "active": false,
      "mode": "none",
      "session_type": "none",
      "duration_minutes": 0,
      "remaining_seconds": 0,
      "expires_at": null,
      "domains_count": 0,
      "pending_unlock": null
    }
    ```
*   **Response JSON (Active Whitelist Session)**:
    ```json
    {
      "status": "ok",
      "active": true,
      "mode": "whitelist",
      "session_type": "standard",
      "duration_minutes": 60,
      "remaining_seconds": 3542,
      "expires_at": "2026-05-22 17:15:00",
      "domains_count": 12,
      "pending_unlock": null
    }
    ```

### 2. start
Starts a new blocking session.
*   **Request JSON**:
    ```json
    {
      "action": "start",
      "duration_minutes": 90,
      "mode": "blacklist",
      "session_type": "standard",
      "groups": ["social"]
    }
    ```
*   **Response JSON**:
    ```json
    {
      "status": "ok",
      "message": "Blacklist session started successfully.",
      "duration_minutes": 90,
      "mode": "blacklist"
    }
    ```

### 3. stop
Requests the termination of an active session. If an unlock security passphrase has been set, it must be provided. This starts a **20-minute countdown delay** before the session terminates.
*   **Request JSON**:
    ```json
    {
      "action": "stop",
      "key": "my_passphrase"
    }
    ```
*   **Response JSON**:
    ```json
    {
      "status": "pending",
      "message": "Unlock request verified. Session will end at 17:35:00 (20-minute delay).",
      "pending_unlock_seconds": 1200,
      "pending_unlock_at": "17:35:00"
    }
    ```

### 4. get_settings
Retrieves the application's configuration options.
*   **Request JSON**:
    ```json
    {
      "action": "get_settings"
    }
    ```
*   **Response JSON**:
    ```json
    {
      "status": "ok",
      "settings": {
        "sound_start": "bell.mp3",
        "sound_rescue": "alarm.mp3",
        "sound_unlock": "success.mp3",
        "sound_break": "chime.mp3",
        "sound_end": "tada.mp3",
        "sound_scheduled": "notify.mp3",
        "sound_blocked": "denied.mp3",
        "intent_notification_enabled": true,
        "intent_notification_interval": 30
      }
    }
    ```

### 5. save_settings
Saves modified configurations.
*   **Request JSON**:
    ```json
    {
      "action": "save_settings",
      "settings": {
        "sound_start": "notify.mp3",
        "intent_notification_enabled": false
      }
    }
    ```
*   **Response JSON**:
    ```json
    {
      "status": "ok",
      "message": "Settings saved successfully."
    }
    ```

### 6. get_sounds
Lists the files inside the sounds directory.
*   **Request JSON**:
    ```json
    {
      "action": "get_sounds"
    }
    ```
*   **Response JSON**:
    ```json
    {
      "status": "ok",
      "sounds": ["alarm.mp3", "bell.mp3", "chime.mp3", "notify.mp3", "success.mp3"]
    }
    ```

### 7. delete_sound
Deletes a specific sound file.
*   **Request JSON**:
    ```json
    {
      "action": "delete_sound",
      "filename": "notify.mp3"
    }
    ```
*   **Response JSON**:
    ```json
    {
      "status": "ok",
      "message": "Sound 'notify.mp3' deleted successfully."
    }
    ```
