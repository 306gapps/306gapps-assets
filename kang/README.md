# Kanged payloads

Files shipped that were taken from elsewhere rather than dumped from a Pixel
image -- from another gapps distribution, or an older release.

Everything else in a release is extracted from the OTA image named in its
manifest, and is refreshed every time that device gets a new build. What is here
is not: Google no longer ships these, so there is no image to take them from,
and they are pinned at whatever version was last published.

A kanged file is marked `"kanged": true` in the manifest, so it is obvious in
a package listing which payloads are frozen and will never be refreshed.

| file | package | notes |
| --- | --- | --- |
| `GoogleContactsSyncAdapter.apk` | `com.google.android.syncadapters.contacts` | Google-signed, version 2021.x |
| `GoogleCalendarSyncAdapter.apk` | `com.google.android.syncadapters.calendar` | Google-signed, version 2021.x |

Neither appears in any Pixel image from Android 13 through 17 -- modern GMS
handles account sync itself. They are offered because some ROMs still expect the
standalone adapters, and are excluded by default for that reason.
