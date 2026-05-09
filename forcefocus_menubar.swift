import Cocoa
import WebKit
import Foundation

// MARK: - Status Item Manager
class StatusBarItemManager {
    static let shared = StatusBarItemManager()
    private init() {}
    
    var statusItem: NSStatusItem!
    
    func createStatusItem() -> NSStatusItem {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "⚡ FF"
        item.button?.action = #selector(AppDelegate.togglePopover(_:))
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        return item
    }
}

// MARK: - Main Application Delegate
class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate, WKScriptMessageHandler {
    var statusItem: NSStatusItem!
    var popover: NSPopover!
    var timer: Timer?
    var webView: WKWebView?
    var errorCount = 0
    var isCurrentlyActive = false
    var currentPollInterval = 5.0
    var lastStatus: [String: Any]? = nil
    
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
        
        // Start polling timer
        scheduleTimer(interval: currentPollInterval)
        
        // Hide dock icon
        NSApp.setActivationPolicy(.accessory)
    }
    
    func setupWebView() {
        let vc = NSViewController()
        let config = WKWebViewConfiguration()
        
        // Enable developer tools for debugging
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        
        // Setup messaging
        config.userContentController.add(self, name: "nativeCallback")
        
        webView = WKWebView(frame: NSMakeRect(0, 0, 320, 540), configuration: config)
        webView?.navigationDelegate = self
        webView?.uiDelegate = self
        webView?.setValue(false, forKey: "drawsBackground")
        
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
        guard let url = URL(string: "http://127.0.0.1:7070/menubar") else { return }
        webView?.load(URLRequest(url: url))
    }
    
    func scheduleTimer(interval: TimeInterval) {
        // Obsolete: SSE from WebView now drives state updates via nativeCallback
    }
    
    func popoverWillShow(_ notification: Notification) {
        webView?.evaluateJavaScript("window.onPopoverShow && window.onPopoverShow()")
    }
    
    func popoverDidClose(_ notification: Notification) {
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
    
    @objc func pollStatus() {
        // Obsolete: Replaced by JS SSE syncState
    }
    
    func handleOffline(error: Error) {
        errorCount += 1
        if errorCount > 3 {
            statusItem.button?.title = "⚠️ FF Offline"
        }
    }
    
    func updateStatusDisplay(_ json: [String: Any]) {
        guard let active = json["active"] as? Bool else {
            statusItem.button?.title = "⚡ FF"
            return
        }
        
        if active {
            var rem = json["remaining_seconds"] as? Int ?? 0
            let sessionType = json["session_type"] as? String ?? "standard"
            let mode = json["mode"] as? String ?? "blacklist"
            
            if sessionType == "rescue" {
                statusItem.button?.title = "🛡️ RESCUE"
                return
            }
            
            if sessionType == "pomodoro",
               let phaseRem = json["pomo_phase_remaining"] as? Int {
                rem = phaseRem
            }
            
            let h = rem / 3600
            let m = (rem % 3600) / 60
            let s = rem % 60
            var timeStr = ""
            
            if h > 0 {
                timeStr = String(format: "%d:%02d:%02d", h, m, s)
            } else {
                timeStr = String(format: "%02d:%02d", m, s)
            }
            
            let icon: String
            if sessionType == "pomodoro",
               let phase = json["pomo_phase"] as? String,
               phase == "break" {
                icon = "☕"
            } else if mode == "whitelist" {
                icon = "✅"
            } else {
                icon = "🚫"
            }
            
            statusItem.button?.title = "\(icon) \(timeStr)"
        } else {
            statusItem.button?.title = "⚡ FF"
        }
    }
    
    func adjustPollingRate(_ json: [String: Any]) {
        let isActive = json["active"] as? Bool ?? false
        let newInterval: TimeInterval = isActive ? 1.0 : 5.0
        
        if newInterval != currentPollInterval {
            currentPollInterval = newInterval
            scheduleTimer(interval: currentPollInterval)
        }
    }
    
    func detectStateChanges(_ json: [String: Any]) {
        // Detect significant state changes to trigger UI updates
        if lastStatus?["active"] as? Bool != json["active"] as? Bool ||
            lastStatus?["mode"] as? String != json["mode"] as? String ||
            lastStatus?["session_type"] as? String != json["session_type"] as? String {
            // Trigger UI refresh when state changes
            NotificationCenter.default.post(name: NSNotification.Name("ForcedFocusStateChanged"), object: json)
        }
        
        lastStatus = json
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
                    detectStateChanges(stateData)
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
    
    func showNotification(title: String, message: String) {
        // Using modern UserNotifications framework would require more complex setup
        // For now, we'll use the system beep as an alternative notification
        NSSound(named: "Ping")?.play()
        
        // Log to console for debugging purposes
        print("Notification: \(title) - \(message)")
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
    
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
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
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()