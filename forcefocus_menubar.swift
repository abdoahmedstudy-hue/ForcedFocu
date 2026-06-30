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
        item.button?.title = "🗿 Focues"
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
    var lastReloadTime: Date?
    var retryWorkItem: DispatchWorkItem?
    
    var displayTimer: Timer?
    var cachedStatusJson: [String: Any]?
    var statusReceivedTime: Date?
    var doneHoldExpiry: Date?
    
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
        if isReloading {
            if let last = lastReloadTime, Date().timeIntervalSince(last) < 5.0 {
                return
            }
        }
        guard let url = URL(string: "http://127.0.0.1:7070/menubar") else { return }
        isReloading = true
        lastReloadTime = Date()
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
            statusItem.button?.title = "⚠️ Focues Offline"
        }
        
        guard retryWorkItem == nil else { return }
        let work = DispatchWorkItem { [weak self] in
            self?.retryWorkItem = nil
            self?.loadMenuBarPage()
        }
        retryWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0, execute: work)
    }
    
    func updateStatusDisplay(_ json: [String: Any]) {
        self.cachedStatusJson = json
        self.statusReceivedTime = Date()
        self.renderCurrentState()
    }
    
    func formatTime(seconds: Int) -> String {
        if seconds <= 0 { return "Done" }
        if seconds <= 60 { return "\(seconds)s" }
        if seconds > 3600 {
            let h = seconds / 3600
            let m = (seconds % 3600) / 60
            return m > 0 ? "\(h)h \(m)m" : "\(h)h"
        }
        return "\(Int(ceil(Double(seconds) / 60.0)))m"
    }

    func renderCurrentState() {
        guard let json = cachedStatusJson, let statusReceivedTime = statusReceivedTime else { return }
        
        if let expiry = doneHoldExpiry, Date() < expiry {
            return
        }

        func setTitle(icon: String, text: String) {
            let fullText = icon.isEmpty ? text : "\(icon) \(text)"
            if statusItem.button?.title != fullText {
                let textFont = NSFont.monospacedDigitSystemFont(ofSize: 13.0, weight: .regular)
                let iconFont = NSFont.systemFont(ofSize: 14.3, weight: .regular)
                
                let attrString = NSMutableAttributedString(string: fullText)
                let fullRange = NSRange(location: 0, length: fullText.utf16.count)
                attrString.addAttribute(.foregroundColor, value: NSColor.labelColor, range: fullRange)
                
                if !icon.isEmpty {
                    let iconRange = NSRange(location: 0, length: icon.utf16.count)
                    let textRange = NSRange(location: icon.utf16.count, length: fullText.utf16.count - icon.utf16.count)
                    attrString.addAttribute(.font, value: iconFont, range: iconRange)
                    attrString.addAttribute(.font, value: textFont, range: textRange)
                    attrString.addAttribute(.baselineOffset, value: -1.0, range: iconRange)
                } else {
                    attrString.addAttribute(.font, value: textFont, range: fullRange)
                }
                
                statusItem.button?.attributedTitle = attrString
                statusItem.button?.title = fullText
            }
        }

        let active = json["active"] as? Bool ?? false
        manageActivity(active: active)
        
        if displayTimer == nil {
            displayTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
                self?.renderCurrentState()
            }
            if let timer = displayTimer {
                RunLoop.main.add(timer, forMode: .common)
            }
        }

        let elapsed = Int(Date().timeIntervalSince(statusReceivedTime))

        if active {
            let sessionType = json["session_type"] as? String ?? "standard"
            let mode = json["mode"] as? String ?? "blacklist"
            
            let icon: String
            if sessionType == "prayer" { icon = "☾" }
            else if sessionType == "rescue" { icon = "☠" }
            else if sessionType == "pomodoro" {
                let phase = json["pomo_phase"] as? String
                icon = phase == "break" ? "☺" : "☃"
            } else if mode == "whitelist" { icon = "◌" }
            else { icon = "𖤞" }
            
            var totalRem = 0
            if sessionType == "pomodoro" {
                totalRem = json["pomo_phase_remaining"] as? Int ?? 0
            } else {
                totalRem = json["remaining_seconds"] as? Int ?? (json["total_duration_seconds"] as? Int ?? 0)
            }
            
            let currentRem = max(0, totalRem - elapsed)
            if currentRem <= 0 && totalRem > 0 {
                if doneHoldExpiry == nil {
                    doneHoldExpiry = Date().addingTimeInterval(2.0)
                }
            } else {
                doneHoldExpiry = nil
            }
            
            setTitle(icon: icon, text: formatTime(seconds: currentRem))
        } else {
            doneHoldExpiry = nil
            
            var cueIcon = ""
            var cueText = ""
            
            // Priority 1: Prayer countdown (⇣ within 5 minutes)
            if let prayer = json["prayer"] as? [String: Any],
               let prayerSeconds = prayer["next_prayer_seconds"] as? Int,
               let prayerName = prayer["next_prayer_name"] as? String {
                let rem = prayerSeconds - elapsed
                if rem > 0 && rem <= 300 {
                    cueIcon = "☾"
                    cueText = "\(prayerName) ⇣ \(formatTime(seconds: rem))"
                }
            }
            
            // Priority 2: Schedule countdown (⇣ within 5 minutes)
            if cueText.isEmpty,
               let schedules = json["schedules"] as? [[String: Any]],
               let first = schedules.first,
               let startIso = first["start_time_iso"] as? String {
                // Handle both naive (from Python) and timezone-aware ISO strings
                if let startDate = parseISO8601(startIso) {
                    let rem = Int(startDate.timeIntervalSinceNow)
                    if rem > 0 && rem <= 300 {
                        cueIcon = "🗿"
                        cueText = "SCHEDULED ⇣ \(formatTime(seconds: rem))"
                    }
                }
            }
            
            if !cueText.isEmpty {
                setTitle(icon: cueIcon, text: cueText)
            } else {
                setTitle(icon: "🗿", text: "Focues")
                displayTimer?.invalidate()
                displayTimer = nil
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
    
    func parseISO8601(_ string: String) -> Date? {
        // Try standard ISO8601 with timezone first
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = isoFormatter.date(from: string) { return date }
        
        isoFormatter.formatOptions = [.withInternetDateTime]
        if let date = isoFormatter.date(from: string) { return date }
        
        // Fallback: naive datetime from Python (no timezone → assume local)
        let df = DateFormatter()
        df.locale = Locale(identifier: "en_US_POSIX")
        df.timeZone = TimeZone.current
        for fmt in ["yyyy-MM-dd'T'HH:mm:ss.SSSSSS", "yyyy-MM-dd'T'HH:mm:ss"] {
            df.dateFormat = fmt
            if let date = df.date(from: string) { return date }
        }
        return nil
    }
    
    func startNativePolling() {
        statusTimer?.invalidate()
        statusTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { [weak self] _ in
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
        center.requestAuthorization(options: [.alert, .sound, .badge]) { [weak self] granted, error in
            if granted {
                let content = UNMutableNotificationContent()
                content.title = title
                content.body = message
                content.sound = .default
                let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
                center.add(request) { addError in
                    if let addError = addError {
                        NSLog("ForcedFocus notification delivery failed: %@", addError.localizedDescription)
                        self?.showNotificationFallback(title: title, message: "macOS notification delivery failed. Check notification settings.")
                    }
                }
            } else if let error = error {
                NSLog("ForcedFocus notification permission failed: %@", error.localizedDescription)
                self?.showNotificationFallback(title: title, message: "macOS notification permission failed. Check notification settings.")
            } else {
                NSLog("ForcedFocus notification permission denied; notification fallback required.")
                self?.showNotificationFallback(title: title, message: "macOS notifications are disabled. ForcedFocus will keep showing in-app alerts.")
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
        // Cancel any pending retry since we've successfully recovered
        retryWorkItem?.cancel()
        retryWorkItem = nil
        // Restore menubar icon if we were showing offline warning
        if statusItem.button?.title == "⚠️ Focues Offline" {
            statusItem.button?.title = "🗿 Focues"
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
