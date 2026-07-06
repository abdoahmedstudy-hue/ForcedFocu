import Cocoa
import WebKit
import Foundation
import UserNotifications

// MARK: - Status Item Manager
class StatusBarItemManager {
    static let shared = StatusBarItemManager()
    private init() {}
    
    var statusItem: NSStatusItem!
    
    func createStatusItem() -> NSStatusItem {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.font = NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .regular)
        item.button?.title = "🗿 Focus"
        item.button?.action = #selector(AppDelegate.togglePopover(_:))
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        return item
    }
}

// MARK: - Main Application Delegate
class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate, WKScriptMessageHandler {
    var statusItem: NSStatusItem!
    var popover: NSPopover!
    var webView: WKWebView?
    var errorCount = 0
    var isCurrentlyActive = false
    var statusTimer: Timer?
    var activityToken: NSObjectProtocol?
    var lastCloseTime: Date?
    var isReloading = false

    func parseISO8601Date(_ str: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        
        let formats = [
            "yyyy-MM-dd'T'HH:mm:ss.SSSSSS",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm:ssZZZZZ",
            "yyyy-MM-dd'T'HH:mm:ss.SSSZZZZZ"
        ]
        for format in formats {
            formatter.dateFormat = format
            if let date = formatter.date(from: str) {
                return date
            }
        }
        return nil
    }
    
    func applicationDidFinishLaunching(_ aNotification: Notification) {
        // Create status item
        statusItem = StatusBarItemManager.shared.createStatusItem()
        
        // Setup popover
        popover = NSPopover()
        popover.contentSize = NSSize(width: 320, height: 540)
        popover.behavior = .transient
        popover.delegate = self
        
        // Setup view controller with webview
        setupWebView()
        
        // Native UI updates driven via JS nativeCallback SSE, plus native fallback polling
        startNativePolling()
        
        // Hide dock icon
        NSApp.setActivationPolicy(.accessory)
    }
    
    func setupWebView() {
        let vc = NSViewController()
        let config = WKWebViewConfiguration()
        
        // Enable developer tools for debugging
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        
        // Setup messaging
        config.userContentController.add(WeakScriptMessageHandler(delegate: self), name: "nativeCallback")
        
        // Read API token if available and inject it at document start
        var token = ""
        if let fileToken = try? String(contentsOfFile: "/etc/forcefocus/api_token", encoding: .utf8) {
            token = fileToken.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let tokenScriptContent = "window.apiToken = '\(token)';"
        let tokenScript = WKUserScript(source: tokenScriptContent, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        config.userContentController.addUserScript(tokenScript)
        
        webView = WKWebView(frame: NSMakeRect(0, 0, 320, 540), configuration: config)
        webView?.navigationDelegate = self
        webView?.uiDelegate = self
        webView?.setValue(false, forKey: "drawsBackground")
        webView?.autoresizingMask = [.width, .height]
        
        // Create visual effect view
        let effectView = NSVisualEffectView(frame: NSMakeRect(0, 0, 320, 540))
        effectView.material = .popover
        effectView.blendingMode = .behindWindow
        effectView.state = .active
        effectView.addSubview(webView!)
        
        vc.view = effectView
        popover.contentViewController = vc
        
        // Load the menubar page
        loadMenuBarPage()
    }
    
    func loadMenuBarPage() {
        guard !isReloading else { return }
        guard let url = URL(string: "http://127.0.0.1:7070/menubar") else { return }
        isReloading = true
        webView?.load(URLRequest(url: url))
    }
    

    
    func popoverWillShow(_ notification: Notification) {
        webView?.evaluateJavaScript("window.onPopoverShow && window.onPopoverShow()")
    }
    
    func popoverDidShow(_ notification: Notification) {
        if let window = popover.contentViewController?.view.window {
            window.makeKey()
        }
        if let web = webView {
            web.window?.makeFirstResponder(web)
        }
    }
    
    func popoverDidClose(_ notification: Notification) {
        lastCloseTime = Date()
        webView?.evaluateJavaScript("window.onPopoverHide && window.onPopoverHide()")
    }
    
    @objc func togglePopover(_ sender: AnyObject?) {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp {
            showContextMenu()
            return
        }
        
        if popover.isShown {
            closePopover(sender)
        } else {
            if let lastClose = lastCloseTime, Date().timeIntervalSince(lastClose) < 0.2 {
                return
            }
            showPopover(sender)
        }
    }
    
    func showContextMenu() {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open Full Dashboard", action: #selector(openDashboard), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Refresh MenuBar", action: #selector(refreshMenuBar), keyEquivalent: "r"))
        menu.addItem(NSMenuItem(title: "About ForcedFocus", action: #selector(showAbout), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit Menu Bar App", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        
        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil
    }
    
    @objc func openDashboard() {
        if let url = URL(string: "http://127.0.0.1:7070") {
            NSWorkspace.shared.open(url)
        }
    }
    
    @objc func refreshMenuBar() {
        loadMenuBarPage()
    }
    
    @objc func showAbout() {
        let alert = NSAlert()
        alert.messageText = "ForcedFocus MenuBar"
        alert.informativeText = "Version 2.1.0\n\nUnbreakable productivity for macOS."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
    
    func showPopover(_ sender: AnyObject?) {
        guard let button = statusItem.button else { return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
    }
    
    func closePopover(_ sender: AnyObject?) {
        popover.performClose(sender)
    }
    

    
    func handleOffline(error: Error) {
        isReloading = false
        errorCount += 1
        if errorCount >= 3 {
            if let img = NSImage(systemSymbolName: "exclamationmark.triangle.fill", accessibilityDescription: nil) {
                img.isTemplate = true
                statusItem.button?.image = img
            }
            statusItem.button?.imagePosition = .imageLeft
            statusItem.button?.title = "Offline"
        }
        
        // Schedule retry load after 3 seconds to recover when daemon boots
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
            self?.loadMenuBarPage()
        }
    }
    
    func updateStatusDisplay(_ json: [String: Any]) {
        func setTitle(_ newTitle: String) {
            if statusItem.button?.title != newTitle {
                statusItem.button?.title = newTitle
            }
        }

        let active = json["active"] as? Bool ?? false
        let sessionType = json["session_type"] as? String ?? "standard"
        let mode = json["mode"] as? String ?? "blacklist"
        let pomoPhase = json["pomo_phase"] as? String
        
        manageActivity(active: active)
        
        if active {
            var rem = json["remaining_seconds"] as? Int ?? 0
            
            if sessionType == "pomodoro" && pomoPhase == "done" {
                if let img = NSImage(systemSymbolName: "checkmark.seal.fill", accessibilityDescription: nil) {
                    img.isTemplate = true
                    statusItem.button?.image = img
                }
                statusItem.button?.imagePosition = .imageLeft
                setTitle("Done")
                return
            }
            
            if sessionType == "rescue" {
                if let img = NSImage(systemSymbolName: "lock.fill", accessibilityDescription: nil) {
                    img.isTemplate = true
                    statusItem.button?.image = img
                }
                statusItem.button?.imagePosition = .imageLeft
                setTitle("RESCUE")
                return
            }
            
            if sessionType == "prayer" {
                statusItem.button?.image = nil
                setTitle("🕌 PRAYER")
                return
            }
            
            if sessionType == "pomodoro",
               let phaseRem = json["pomo_phase_remaining"] as? Int {
                rem = phaseRem
            }
            
            let h = rem / 3600
            let m = (rem % 3600) / 60
            var timeStr = ""
            
            // To prevent the menu bar from visually ticking every single second (which is distracting),
            // we only show hours and minutes. We show seconds only if under 1 minute.
            if h == 0 && m == 0 {
                let s = rem % 60
                timeStr = String(format: "%2ds", s)
            } else if h > 0 {
                timeStr = String(format: "%dh %02dm", h, m)
            } else {
                timeStr = String(format: "%2dm", m)
            }
            
            let iconName: String
            if h == 0 && m == 0 {
                // Final minute sprint
                iconName = "hourglass.bottomhalf.filled"
            } else if sessionType == "pomodoro", pomoPhase == "break" {
                iconName = "cup.and.saucer.fill"
            } else if mode == "whitelist" {
                iconName = "target"
            } else {
                iconName = "brain.head.profile"
            }
            
            if let img = NSImage(systemSymbolName: iconName, accessibilityDescription: nil) {
                img.isTemplate = true
                statusItem.button?.image = img
            }
            statusItem.button?.imagePosition = .imageLeft
            setTitle(timeStr)
        } else {
            // Idle state: Check if a schedule is starting in under 5 minutes
            var scheduleCountdownShown = false
            if let schedules = json["schedules"] as? [[String: Any]],
               let firstSch = schedules.first,
               let startTimeStr = firstSch["start_time_iso"] as? String,
               let startTime = parseISO8601Date(startTimeStr) {
                let now = Date()
                let diff = startTime.timeIntervalSince(now)
                if diff > 0 && diff <= 300 {
                    let diffInt = Int(diff)
                    let m = diffInt / 60
                    let s = diffInt % 60
                    
                    let timeStr: String
                    if m == 0 {
                        timeStr = String(format: "%2ds", s)
                    } else {
                        timeStr = String(format: "%2dm", m)
                    }
                    
                    if let img = NSImage(systemSymbolName: "arrow.down", accessibilityDescription: nil) {
                        img.isTemplate = true
                        statusItem.button?.image = img
                    }
                    statusItem.button?.imagePosition = .imageLeft
                    setTitle(timeStr)
                    scheduleCountdownShown = true
                }
            }
            
            var prayerCountdownShown = false
            if !scheduleCountdownShown, let prayerSecs = json["next_prayer_seconds"] as? Int, prayerSecs <= 300 {
                let m = prayerSecs / 60
                let s = prayerSecs % 60
                let timeStr: String
                if m == 0 {
                    timeStr = String(format: "%2ds", s)
                } else {
                    timeStr = String(format: "%2dm", m)
                }
                if let img = NSImage(systemSymbolName: "arrow.down", accessibilityDescription: nil) {
                    img.isTemplate = true
                    statusItem.button?.image = img
                }
                statusItem.button?.imagePosition = .imageLeft
                setTitle("🕌 " + timeStr)
                prayerCountdownShown = true
            }
            
            if !scheduleCountdownShown && !prayerCountdownShown {
                statusItem.button?.image = nil
                setTitle("🗿 Focus")
            }
        }
    }
    
    func manageActivity(active: Bool) {
        if active && activityToken == nil {
            activityToken = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .latencyCritical], reason: "ForcedFocus Menu Bar Sync")
        } else if !active && activityToken != nil {
            if let token = activityToken {
                ProcessInfo.processInfo.endActivity(token)
            }
            activityToken = nil
        }
    }
    
    func startNativePolling() {
        statusTimer?.invalidate()
        statusTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.fetchStatus()
        }
        // Ensure timer fires even when the user is interacting with the menu
        if let timer = statusTimer {
            RunLoop.main.add(timer, forMode: .common)
        }
    }
    
    func fetchStatus() {
        guard let url = URL(string: "http://127.0.0.1:7070/api/status") else { return }
        let task = URLSession.shared.dataTask(with: url) { [weak self] data, response, error in
            if let error = error {
                DispatchQueue.main.async {
                    self?.handleOffline(error: error)
                }
                return
            }
            if let data = data,
               let json = try? JSONSerialization.jsonObject(with: data, options: []) as? [String: Any] {
                DispatchQueue.main.async {
                    self?.errorCount = 0
                    self?.updateStatusDisplay(json)
                }
            }
        }
        task.resume()
    }
    
    
    // MARK: - WKScriptMessageHandler
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "nativeCallback", let body = message.body as? [String: Any] {
            handleNativeCallback(body)
        }
    }
    
    func handleNativeCallback(_ data: [String: Any]) {
        // Handle callbacks from the web interface
        if let action = data["action"] as? String {
            switch action {
            case "playSound":
                if let sound = data["sound"] as? String {
                    playSystemSound(named: sound)
                }
            case "showNotification":
                if let title = data["title"] as? String,
                   let message = data["message"] as? String {
                    showNotification(title: title, message: message)
                }
            case "syncState":
                if let stateData = data["data"] as? [String: Any] {
                    errorCount = 0
                    updateStatusDisplay(stateData)
                }
            default:
                break
            }
        }
    }
    
    func playSystemSound(named: String) {
        // Play system sounds or notifications
        switch named {
        case "success":
            NSSound(named: "Ping")?.play()
        case "warning":
            NSSound(named: "Sosumi")?.play()
        case "error":
            NSSound(named: "Basso")?.play()
        default:
            NSSound(named: "Ping")?.play()
        }
    }
    
    func jsStringLiteral(_ value: String) -> String {
        guard
            let data = try? JSONSerialization.data(withJSONObject: [value], options: []),
            let wrapped = String(data: data, encoding: .utf8),
            wrapped.count >= 2
        else {
            return "\"Notification fallback unavailable.\""
        }
        return String(wrapped.dropFirst().dropLast())
    }
    
    func showNotificationFallback(title: String, message: String) {
        let fallback = "\(title): \(message)"
        let js = "window.showNotificationFallback && window.showNotificationFallback(\(jsStringLiteral(fallback)));"
        DispatchQueue.main.async { [weak self] in
            self?.webView?.evaluateJavaScript(js, completionHandler: nil)
        }
    }
    
    func showNotification(title: String, message: String) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            if granted {
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = message
                content.sound = .default
                let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
                center.add(request) { addError in
                    if let addError = addError {
                        NSLog("ForcedFocus notification delivery failed: %@", addError.localizedDescription)
                        self.showNotificationFallback(title: title, message: "macOS notification delivery failed. Check notification settings.")
                    }
                }
            } else if let error = error {
                NSLog("ForcedFocus notification permission failed: %@", error.localizedDescription)
                self.showNotificationFallback(title: title, message: "macOS notification permission failed. Check notification settings.")
            } else {
                NSLog("ForcedFocus notification permission denied; notification fallback required.")
                self.showNotificationFallback(title: title, message: "macOS notifications are disabled. ForcedFocus will keep showing in-app alerts.")
            }
        }
    }
}

// MARK: - Web View Delegates
extension AppDelegate: WKNavigationDelegate, WKUIDelegate {
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.navigationType == .linkActivated,
           let url = navigationAction.request.url {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
    
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        isReloading = false
        handleOffline(error: error)
    }
    
    @objc func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        isReloading = false
        handleOffline(error: error)
    }
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        isReloading = false
        errorCount = 0
        if statusItem.button?.title == "Offline" {
            statusItem.button?.image = nil
            statusItem.button?.title = "🗿 Focus"
        }
        
        // Inject JavaScript to communicate with native layer
        let js = """
        window.nativeCallback = function(data) {
            window.webkit.messageHandlers.nativeCallback.postMessage(data);
        };
        """
        webView.evaluateJavaScript(js, completionHandler: nil)
    }
}

// MARK: - Main Application Entry Point

// Parse CLI arguments for dual-purpose notification binary
let args = UserDefaults.standard
if let notifyTitle = args.string(forKey: "notify-title") {
    let notifyBody = args.string(forKey: "notify-body") ?? ""
    
    let center = UNUserNotificationCenter.current()
    center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
        if granted {
            let content = UNMutableNotificationContent()
            content.title = notifyTitle
            content.body = notifyBody
            content.sound = .default
            
            let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            center.add(request) { _ in
                exit(0)
            }
        } else {
            exit(1)
        }
    }
    // Spin the runloop briefly to allow async notification delivery before exiting
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 2.0))
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

// MARK: - Weak Script Message Handler Proxy
class WeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    weak var delegate: WKScriptMessageHandler?
    
    init(delegate: WKScriptMessageHandler) {
        self.delegate = delegate
        super.init()
    }
    
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        delegate?.userContentController(userContentController, didReceive: message)
    }
}
