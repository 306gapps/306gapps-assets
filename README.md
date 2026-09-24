# 306gapps-assets

Google apps dumped from Pixel OTA images, published as manifests plus payloads
for [306gapps](https://github.com/306gapps/306gapps) to build from.

A workflow watches Google's OTA listing. For every supported Android version it
finds the newest generic Pixel build, and for any it has not seen it downloads
the OTA, splits `payload.bin`, extracts the partitions, sorts the files into
packages, and publishes a release.

## Support window

**Android 13 through the current release.** The window is defined by which
`packages/a<N>.yaml` files exist -- add a definition file and that version is
covered, delete one and it is not. Nothing else needs changing.

| Android | API | definitions | verified against a real dump |
| --- | --- | --- | --- |
| 17 | 37 | `packages/a17.yaml` | yes - `cubs` CD1A.260905.001.B1 |
| 16 | 36 | `packages/a16.yaml` | not yet |
| 15 | 35 | `packages/a15.yaml` | not yet |
| 14 | 34 | `packages/a14.yaml` | not yet |
| 13 | 33 | `packages/a13.yaml` | not yet |

Only the Android 17 definitions have been checked against an actual dump. The
rest were derived from them and are hypotheses: Google moves apps between
`/product` and `/system_ext` and renames directories between releases. The first
workflow run for each version refuses to publish on an API mismatch and lists
every unclaimed apk, apex and jar; work through that list, then delete the notice
at the top of the file.

A structural change worth knowing about: on Android 17 the bulk of GMS Core
ships as a 148 MB **apex** (`product/apex/com.google.android.gmssystem*.apex`)
and `priv-app/PrebuiltGmsCore/` holds only the Chimera modules. Older releases
ship it as an apk. Every definition file carries both globs, so whichever the
dump actually contains is what gets claimed.

## Layout

The payloads do **not** live in git. A full gapps set is roughly a gigabyte per
build, and git keeps every version of every binary forever — a year of monthly
dumps would put this repo into the tens of gigabytes and make it unclonable.

| where | what |
| --- | --- |
| `main` | tooling, package definitions, and `index.json` — the catalogue the builder reads first |
| `a16`, `a17`, … | one branch per Android version, holding `releases/<id>/manifest.json` |
| GitHub Releases | the actual payloads, one release per Pixel build |

So git holds only small, diffable, reviewable text, and the builder pulls just
the payloads a user actually selected.

## Package definitions

`packages/a<version>.yaml` decides what a "package" is. Each one claims files
from the dump by glob:

```yaml
  - id: gsa
    name: Google Search and Assistant
    category: apps
    requires: [gmscore]
    removes:
      - product/app/QuickSearchBox
    include:
      - product/priv-app/Velvet/**
      - product/etc/permissions/com.google.android.googlequicksearchbox.xml
```

| key | meaning |
| --- | --- |
| `include` | globs claiming files; `*` stops at `/`, `**` does not |
| `requires` | packages pulled in automatically |
| `conflicts` | packages that cannot be installed alongside |
| `removes` | AOSP install paths the installer deletes (or masks, for modules) |
| `required` | always installed, cannot be deselected |
| `default` | starts selected in the picker |
| `props` | build properties to apply; `{gms_version}` is read from the dump |

A file may be claimed by exactly one package. Anything left unclaimed is
reported, and unclaimed **apks** raise a workflow warning — that is how a newly
added Google app surfaces instead of silently going missing.

## Adding a new Android version

1. Copy the previous `packages/aN.yaml` to the new version and update `android:`.
2. Trigger `dump` manually with the new major version.
3. It will fail if the definitions declare the wrong API level, and warn about
   every apk the definitions do not claim. Work through that list.
4. Re-run until the warnings are ones you have decided to ignore.

## Tools

| tool | what it does |
| --- | --- |
| `tools/pixel.py` | parse Google's OTA listing, pick the newest generic build |
| `tools/plan_dumps.py` | work out which supported versions need a dump |
| `tools/fetch_busybox.py` | republish the static busybox the installer bundles |
| `tools/extract.py` | OTA zip → `payload.bin` → partition images → file tree |
| `tools/build_manifest.py` | sort the tree into packages, emit `manifest.json` + payloads |
| `tools/publish_index.py` | add a release to `index.json`, retire old ones |
| `tools/rebuild_index.py` | reconstruct `index.json` from what is actually published |

Each runs standalone, so the pipeline can be driven by hand when the workflow
needs debugging:

```
python3 tools/plan_dumps.py --packages packages --index index.json
python3 tools/pixel.py --list-devices
python3 tools/pixel.py --device cubs > build.json
python3 tools/extract.py --url "$(jq -r .url build.json)" \
                         --sha256 "$(jq -r .sha256 build.json)"
python3 tools/build_manifest.py --tree work/tree --packages packages/a17.yaml \
        --assets out/assets --out out/manifest.json \
        --device cubs --build "$(jq -r .build_id build.json)"
```

`extract.py` needs `payload-dumper-go`, `erofs-utils` (Android 13+ images) and
`e2fsprogs` (older ext4 images). Building `payload-dumper-go` also needs
`liblzma-dev`, because it depends on a cgo xz binding.
`python3 tools/extract.py --check-tools` reports what is missing.

A dump is disk-hungry: the OTA, the payload, the split images and the extracted
tree are each several gigabytes. Pass `--reclaim` to delete each one as soon as
it has been consumed, which roughly halves the peak and is what CI uses. Without
it, nothing is deleted and a second run reuses the intermediates.

## Testing

```
cd tools && python3 -m unittest discover -p 'test_*.py'
```

The glob matcher and the OTA parser are both covered. The extraction step is
exercised by the workflow rather than by unit tests, since it needs multi-gigabyte
inputs.

## busybox

The recovery installer bundles a static busybox so it runs against one
predictable toolset rather than whatever a given recovery provides. We
republish the build from [Magisk](https://github.com/topjohnwu/Magisk), which is
well tested across exactly the devices and recoveries this targets.

BusyBox is GPLv2. Republishing the binary carries the obligation to offer the
corresponding source, which the `NOTICE` published alongside it does, and which
the builder copies into every recovery zip.

## Licensing

The apps published here are Google's, under Google's terms. Redistributing them
is not something Google licenses — this repo exists on the same footing as every
other gapps distribution. Fork it and run your own if that matters to you.
