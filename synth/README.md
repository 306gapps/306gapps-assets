# Synthetic payloads

Generated here, not extracted from anyone's image.

## VerifierBlocker.apk

An empty apk that claims `com.google.android.verifier` and nothing else. It
holds no code (`android:hasCode="false"`) and declares no components.

Android refuses to replace an installed package with one signed by a different
key. Installing this takes the name permanently: the real developer-verification
component can never be installed over it, by the Play Store or anything else.

The signing key was generated inside `tools/mkblocker.py` and discarded when it
exited. It was never written to disk and nobody holds it, which is the property
that makes the block permanent — including for us. `VerifierBlocker.pem` is the
certificate, kept so the signature can be checked:

    unzip -p VerifierBlocker.apk META-INF/CERT.RSA \
      | openssl pkcs7 -inform DER -print_certs -noout

Regenerating the apk produces a *different* key and therefore a different
package, which would not upgrade the one people already have. Do not regenerate
it; if it ever must change, that is a new package name and a deliberate
migration.

For contrast, Google signs the real `VerifierPrebuiltClassic.apk` with
`CN=Android, O=Google Inc.`, SHA-256 fingerprint
`05:0F:40:2B:FA:8B:C4:73:F2:81:04:1A:03:73:CE:4B:56:55:65:35:C2:CC:40:5E:2E:DE:17:97:5E:C0:46:E7`.
This one is
`BC:A9:D4:07:37:72:15:34:01:21:A2:BA:96:25:DE:F6:ED:24:69:1E:C3:05:E9:CE:6A:9D:6F:51:08:92:F4:67`.
