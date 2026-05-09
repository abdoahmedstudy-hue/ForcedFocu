#!/bin/bash
set -e

APP_NAME="ForcedFocusBar"
APP_DIR="$APP_NAME.app"
BIN_DIR="$APP_DIR/Contents/MacOS"
RES_DIR="$APP_DIR/Contents/Resources"
PLIST="$APP_DIR/Contents/Info.plist"

echo "🔨 Building ForcedFocus Menu Bar App..."

# Create directory structure
mkdir -p "$BIN_DIR"
mkdir -p "$RES_DIR"

# Copy Icon
ICON_SRC="./icon/icnsFile_03f04725724b4a02637c68df9e718e76_Complete_Anatomy__Clear_Dark_.icns"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$RES_DIR/AppIcon.icns"
    echo "✅ Applied custom App Icon."
else
    echo "⚠️ No AppIcon.icns found in current directory. Using default."
fi

# Compile Swift code
# Link against AppKit and WebKit
swiftc forcefocus_menubar.swift -o "$BIN_DIR/$APP_NAME" \
    -framework AppKit -framework WebKit -sdk $(xcrun --show-sdk-path)

# Create Info.plist
cat <<EOF > "$PLIST"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.forcefocus.menubar</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.1.0</string>
    <key>CFBundleVersion</key>
    <string>2.1.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSUserNotificationUsageDescription</key>
    <string>ForcedFocus needs to show notifications for session updates.</string>
</dict>
</plist>
EOF

echo "✅ Build complete: $APP_DIR"
echo "You can move it to /Applications or double-click to run!"
