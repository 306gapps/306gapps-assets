#!/usr/bin/env bash
# Build the locale-picker shim from synth/localepicker-shim.
#
# The Pixel setup wizard fires com.google.android.settings.localepicker.
# LOCALE_REGION_PICKER, which only Google's Settings app answers. This priv-app
# answers it, hosts the platform's own language/region picker, and sets the
# system locale via com.android.internal.app.LocalePicker; the wizard re-reads it.
#
# Compiling against the internal picker needs a framework classpath jar (the
# ROM's turbine framework.jar), set via FRAMEWORK_JAR.
#
# Needs javac, and d8/aapt2/apksigner/zipalign (android build-tools) + keytool.
set -euo pipefail
SRC=$(cd "$(dirname "$0")/../synth/localepicker-shim" && pwd)
OUT=${1:-$(dirname "$0")/../synth/LocalePickerShim.apk}
: "${ANDROID_BUILD_TOOLS:?set ANDROID_BUILD_TOOLS to an android build-tools dir}"
: "${ANDROID_JAR:?set ANDROID_JAR to a platform android.jar}"
: "${FRAMEWORK_JAR:=$SRC/framework-classpath.jar}"
: "${JAVAC:=javac}"
[ -f "$FRAMEWORK_JAR" ] || { echo "need FRAMEWORK_JAR (ROM turbine framework.jar) at $FRAMEWORK_JAR"; exit 1; }
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/classes"
"$JAVAC" -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -classpath "$FRAMEWORK_JAR" \
    -d "$work/classes" "$SRC"/src/app/gapps306/localeshim/*.java
"$ANDROID_BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 30 --output "$work" \
    "$work"/classes/app/gapps306/localeshim/*.class
link_args=(link -o "$work/base.apk" --manifest "$SRC/AndroidManifest.xml" -I "$ANDROID_JAR")
if [ -d "$SRC/res" ]; then
    "$ANDROID_BUILD_TOOLS/aapt2" compile --dir "$SRC/res" -o "$work/res.zip"
    link_args+=("$work/res.zip")
fi
"$ANDROID_BUILD_TOOLS/aapt2" "${link_args[@]}"
( cd "$work" && zip -qj base.apk classes.dex )
"$ANDROID_BUILD_TOOLS/zipalign" -f 4 "$work/base.apk" "$work/aligned.apk"
keytool -genkeypair -keystore "$work/ks.jks" -storepass sixgapps -keypass sixgapps -alias o \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=306gapps shim" >/dev/null 2>&1
"$ANDROID_BUILD_TOOLS/apksigner" sign --ks "$work/ks.jks" --ks-pass pass:sixgapps --key-pass pass:sixgapps \
    --out "$OUT" "$work/aligned.apk"
echo "wrote $OUT"
