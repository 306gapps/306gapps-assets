#!/usr/bin/env bash
# Build the Android Auto projection overlay.
#
# SYSTEM_AUTOMOTIVE_PROJECTION is a system-only role: RoleController only accepts
# the app the framework resource config_systemAutomotiveProjection names. A real
# Pixel sets it, so the OTA carries no overlay for it; an AOSP-based ROM that
# leaves it empty rejects Android Auto. This static RRO sets it, the way
# NikGApps does, so Android Auto qualifies for the role.
#
# Needs aapt2, apksigner (android build-tools) and keytool. The key is a
# throwaway: a static overlay on a read-only partition is trusted by location,
# not signature, and is never upgraded.
set -euo pipefail

PKG=app.gapps306.overlay.androidauto
TARGET=com.google.android.projection.gearhead
OUT=${1:-synth/AndroidAutoProjectionOverlay.apk}

: "${ANDROID_BUILD_TOOLS:?set ANDROID_BUILD_TOOLS to an android build-tools dir}"
: "${ANDROID_JAR:?set ANDROID_JAR to a platform android.jar}"
AAPT2="$ANDROID_BUILD_TOOLS/aapt2"
APKSIGNER="$ANDROID_BUILD_TOOLS/apksigner"

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/res/values"
cat > "$work/AndroidManifest.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="$PKG" android:versionCode="1" android:versionName="1">
    <application android:hasCode="false" />
    <overlay android:targetPackage="android" android:priority="99" android:isStatic="true" />
</manifest>
XML
cat > "$work/res/values/config.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="config_systemAutomotiveProjection" translatable="false">$TARGET</string>
</resources>
XML

"$AAPT2" compile --dir "$work/res" -o "$work/c.zip"
"$AAPT2" link -o "$work/unsigned.apk" --manifest "$work/AndroidManifest.xml" \
    -I "$ANDROID_JAR" --auto-add-overlay "$work/c.zip"
keytool -genkeypair -keystore "$work/ks.jks" -storepass x -keypass x -alias o \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=306gapps overlay" >/dev/null 2>&1
"$APKSIGNER" sign --ks "$work/ks.jks" --ks-pass pass:x --key-pass pass:x \
    --out "$OUT" "$work/unsigned.apk"
echo "wrote $OUT"
