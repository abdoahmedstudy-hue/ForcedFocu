# ForcedFocus HTTP REST API Reference 🌐

The local HTTP REST API is hosted on port **7070** (`http://127.0.0.1:7070`). It is accessed by the local web panel and the menubar app helper.

---

## 🔒 Authentication

All mutating requests (POST, PUT, DELETE) must provide the daemon authorization token via request headers:

```http
X-API-Token: <TOKEN_STRING_FROM_/etc/forcefocus/api_token>
```

Non-mutating GET requests (e.g., `/api/status`, `/api/settings`) do not require authentication if accessed from localhost.

---

## 🗺️ Endpoint Index

### 1. `GET /api/status`
Returns the status metadata of the daemon and active schedules.
*   **Response Payload**:
    ```json
    {
      "active": true,
      "mode": "blacklist",
      "session_type": "standard",
      "remaining_seconds": 3600,
      "expires_at": "2026-05-22 18:00:00",
      "schedules": [
        {"id": "sched_1", "recurring": true, "days": [0,1,2,3,4], "time": "09:00", "duration": 480}
      ]
    }
    ```

### 2. `GET /api/stream`
Exposes a **Server-Sent Events (SSE)** channel that streams live updates of the daemon's state (ticks, remaining time, warnings) directly to clients.
*   **Event Output**:
    ```http
    event: tick
    data: {"remaining_seconds": 3599, "active": true}
    ```

### 3. `GET /api/session-domains`
Retrieves a list of all active domain blocks and permitted hosts configured in the current session.
*   **Response Payload**:
    ```json
    {
      "blacklist": ["facebook.com", "instagram.com"],
      "whitelist": []
    }
    ```

### 4. `GET /api/lists`
Returns configured whitelist and blacklist entries in `/etc/forcefocus/lists.json`.
*   **Response Payload**:
    ```json
    {
      "blacklist": ["reddit.com", "twitter.com"],
      "whitelist": ["github.com", "stackoverflow.com"]
    }
    ```

### 5. `GET /api/groups`
Retrieves domain groups mapping names to domains.
*   **Response Payload**:
    ```json
    {
      "work": ["github.com", "gitlab.com"],
      "entertainment": ["netflix.com", "youtube.com"]
    }
    ```

### 6. `POST /api/start`
Starts a blocking session.
*   **Payload (JSON)**:
    ```json
    {
      "duration_minutes": 60,
      "mode": "whitelist",
      "session_type": "standard",
      "groups": ["work"]
    }
    ```
*   **Response**:
    ```json
    {
      "status": "ok",
      "message": "Session started."
    }
    ```

### 7. `POST /api/stop`
Requests session unlock.
*   **Payload (JSON)**:
    ```json
    {
      "key": "unlock_passphrase"
    }
    ```
*   **Response (Starts 20-min Delay)**:
    ```json
    {
      "status": "pending",
      "message": "Unlock request verified. Unblocking in 20 minutes."
    }
    ```

### 8. `POST /api/intent`
Saves current productivity intent message and focal subtasks.
*   **Payload (JSON)**:
    ```json
    {
      "intent": "Implement Modular CLI documentation",
      "tasks": [
        {"id": 1, "title": "Write socket guide", "done": false},
        {"id": 2, "title": "Write REST API guide", "done": false}
      ]
    }
    ```
*   **Response**:
    ```json
    {
      "status": "ok"
    }
    ```

### 9. `POST /api/groups`
Updates or creates a domain group.
*   **Payload (JSON)**:
    ```json
    {
      "name": "social",
      "domains": ["facebook.com", "tiktok.com"]
    }
    ```

### 10. `DELETE /api/groups`
Removes an existing domain group.
*   **Payload (JSON)**:
    ```json
    {
      "name": "social"
    }
    ```

### 11. `GET /api/settings`
Retrieves settings configurations.
*   **Response Payload**: Same as `get_settings` socket command.

### 12. `GET /api/sounds`
Lists sound assets inside `/Volumes/ssd/File/App/ForcedFocus/ForcedFocu/web/sounds`.
*   **Response Payload**: Same as `get_sounds` socket command.
