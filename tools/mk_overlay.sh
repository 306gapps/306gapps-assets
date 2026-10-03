#!/usr/bin/env bash
# Build a static framework RRO from synth/<name>-overlay into synth/<out>.
#
# These set the config_default*/config_system* framework values a Pixel's
# framework carries but an AOSP-based ROM leaves pointing at the apps we replace,
# so a default dialer, SMS app, gallery, assistant and the like are actually
# assigned. Modeled on the per-app overlays NikGApps ships. Static RRO targeting
# android; shipped only with the package it belongs to.
#
# Needs aapt2, apksigner (android build-tools) and keytool. Throwaway key: a
# static overlay on a read-only partition is trusted by position, not signature.
set -euo pipefail
name=${1:?usage: mk_overlay.sh <name> <OutputApk>}
out=${2:?usage: mk_overlay.sh <name> <OutputApk>}
root=$(cd "$(dirname "$0")/.." && pwd)
SRC="$root/synth/$name-overlay"
OUT="$root/synth/$out"
: "${ANDROID_BUILD_TOOLS:?set ANDROID_BUILD_TOOLS to an android build-tools dir}"
: "${ANDROID_JAR:?set ANDROID_JAR to a platform android.jar}"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
"$ANDROID_BUILD_TOOLS/aapt2" compile --dir "$SRC/res" -o "$work/c.zip"
"$ANDROID_BUILD_TOOLS/aapt2" link -o "$work/unsigned.apk" --manifest "$SRC/AndroidManifest.xml" \
    -I "$ANDROID_JAR" --auto-add-overlay "$work/c.zip"
keytool -genkeypair -keystore "$work/ks.jks" -storepass sixgapps -keypass sixgapps -alias o \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=306gapps overlay" >/dev/null 2>&1
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$work/ks.jks" --ks-pass pass:sixgapps --key-pass pass:sixgapps \
    --out "$OUT" "$work/unsigned.apk"
echo "wrote $OUT"
