import AppKit

// The shell receives a menu and emits fixed action IDs. Python owns every operation.
func emit(_ action: String) {
    guard let data = try? JSONSerialization.data(withJSONObject: ["action": action]),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

final class RouterMenu: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var statusItem: NSStatusItem!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            if CommandLine.arguments.count > 1 {
                button.image = templateIcon(CommandLine.arguments[1])
            }
            button.toolTip = "SCG Router"
            button.setAccessibilityLabel("SCG Router controls")
        }
        DispatchQueue.global(qos: .utility).async {
            while let line = readLine() {
                guard line.utf8.count <= 65536,
                      let data = line.data(using: .utf8),
                      let doc = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      doc["schema"] as? Int == 1 else { continue }
                DispatchQueue.main.async { self.update(doc) }
            }
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }

    func templateIcon(_ path: String) -> NSImage? {
        guard let source = NSImage(contentsOfFile: path),
              let pixels = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 36,
                  pixelsHigh: 36, bitsPerSample: 8, samplesPerPixel: 4,
                  hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                  bytesPerRow: 0, bitsPerPixel: 0),
              let context = NSGraphicsContext(bitmapImageRep: pixels) else { return nil }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        source.draw(in: NSRect(x: 0, y: 0, width: 36, height: 36))
        NSGraphicsContext.restoreGraphicsState()
        for y in 0..<36 { for x in 0..<36 {
            guard let color = pixels.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) else { continue }
            let white = min(color.redComponent, color.greenComponent, color.blueComponent)
            pixels.setColor(NSColor(deviceRed: 0, green: 0, blue: 0,
                alpha: (1 - white) * color.alphaComponent), atX: x, y: y)
        }}
        let icon = NSImage(size: NSSize(width: 18, height: 18))
        icon.addRepresentation(pixels)
        icon.isTemplate = true
        return icon
    }

    func build(_ rows: [[String: Any]]) -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        for row in rows {
            let label = row["label"] as? String ?? ""
            if label.isEmpty { menu.addItem(.separator()); continue }
            let entry = NSMenuItem(title: label, action: #selector(selected(_:)), keyEquivalent: "")
            entry.target = self
            entry.representedObject = row["action"] as? String
            entry.isEnabled = row["enabled"] as? Bool ?? false
            entry.state = (row["checked"] as? Bool ?? false) ? .on : .off
            if let children = row["children"] as? [[String: Any]], !children.isEmpty {
                entry.submenu = build(children)
            }
            menu.addItem(entry)
        }
        return menu
    }

    func update(_ doc: [String: Any]) {
        guard let rows = doc["menu"] as? [[String: Any]] else { return }
        let fresh = build(rows)
        if let menu = statusItem.menu {
            // Replace the items in place: a menu opened before the refresh reply
            // shows the new state at once instead of on the next opening.
            menu.removeAllItems()
            for item in fresh.items {
                fresh.removeItem(item)
                menu.addItem(item)
            }
        } else {
            fresh.delegate = self
            statusItem.menu = fresh
        }
        let state = doc["status"] as? String ?? "Status unknown"
        statusItem.button?.toolTip = "SCG Router: " + state
        statusItem.button?.setAccessibilityLabel("SCG Router: " + state)
    }

    @objc func selected(_ sender: NSMenuItem) {
        if let action = sender.representedObject as? String { emit(action) }
    }

    func menuWillOpen(_ menu: NSMenu) { emit("refresh") }
}

let app = NSApplication.shared
let delegate = RouterMenu()
app.delegate = delegate
app.run()
