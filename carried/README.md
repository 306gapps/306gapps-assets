# Carried payloads

Files shipped that do not come from a Pixel dump.

Everything else in a release is extracted from the OTA image named in its
manifest, and is refreshed every time that device gets a new build. What is here
is not: Google no longer ships these, so there is no image to take them from,
and they are pinned at whatever version was last published.

A carried file is marked `"carried": true` in the manifest, so it is obvious in
a package listing which payloads cannot be refreshed.

| file | package | notes |
| --- | --- | --- |
| `GoogleContactsSyncAdapter.apk` | `com.google.android.syncadapters.contacts` | Google-signed, version 2021.x |
| `GoogleCalendarSyncAdapter.apk` | `com.google.android.syncadapters.calendar` | Google-signed, version 2021.x |

Neither appears in any Pixel image from Android 13 through 17 -- modern GMS
handles account sync itself. They are offered because some ROMs still expect the
standalone adapters, and are excluded by default for that reason.
