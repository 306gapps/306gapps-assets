# Reference artifacts

Output from a real dump of `cubs` (Pixel 11) `CD1A.260905.001.B1`, kept so the
package definitions can be revised without re-downloading a 3.8 GB OTA.

- `*-manifest.json` — what `build_manifest.py` produced from that dump
- `*-unclaimed.txt` — every file no package claimed

The unclaimed list is the working document for extending `packages/a17.yaml`.
Most of what is in it is Pixel device firmware (`SystemUIGoogle`,
`TelephonyGoogle`, modem and RIL services, satellite) that correctly does not
belong in a gapps package.
