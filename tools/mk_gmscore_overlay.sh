#!/usr/bin/env bash
# Build the GMS framework overlay from synth/gmscore-overlay/res.
#
# A real Pixel's framework wires GMS as the default provider for network/fused
# location, autofill, credential manager, wallet, nearby and more. AOSP (and
# LineageOS-based ROMs like crDroid) leave those unset, so GMS features degrade
# without this. Static RRO targeting android, the same set NikGApps ships.
#
# Needs aapt2, apksigner (android build-tools) and keytool. Throwaway key: a
# static overlay on a read-only partition is trusted by location, not signature.
set -euo pipefail
SRC=$(cd "$(dirname "$0")/../synth/gmscore-overlay" && pwd)
OUT=${1:-$(dirname "$0")/../synth/GmsCoreOverlay.apk}
: "${ANDROID_BUILD_TOOLS:?set ANDROID_BUILD_TOOLS to an android build-tools dir}"
: "${ANDROID_JAR:?set ANDROID_JAR to a platform android.jar}"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
"$ANDROID_BUILD_TOOLS/aapt2" compile --dir "$SRC/res" -o "$work/c.zip"
"$ANDROID_BUILD_TOOLS/aapt2" link -o "$work/unsigned.apk" --manifest "$SRC/AndroidManifest.xml" \
    -I "$ANDROID_JAR" --auto-add-overlay "$work/c.zip"
keytool -genkeypair -keystore "$work/ks.jks" -storepass x -keypass x -alias o \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=306gapps overlay" >/dev/null 2>&1
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$work/ks.jks" --ks-pass pass:x --key-pass pass:x \
    --out "$OUT" "$work/unsigned.apk"
echo "wrote $OUT"
