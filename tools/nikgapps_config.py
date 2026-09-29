#!/usr/bin/env python3
"""Read a NikGApps .config into the set of packages it installs.

The format is key=value, where a bare key names an app set and a >>key names
one app inside the set that was named last. 0 means leave it out, which is why
a set can be 1 while most of its members are 0 -- crdroid-official has
PixelSpecifics=1 with PixelLauncher=0 under it.
"""

import re

# NikGApps app name -> our package id. Several map to the same id; anything
# absent is something we do not ship as its own package.
NAMES = {
    "AICore": "aicore",
    "AndroidAuto": "androidauto",
    "AndroidDevicePolicy": "devicepolicy",
    "CarrierServices": "carriersetup",
    "DevicePersonalizationServices": "aiai",
    "DigitalWellbeing": "wellbeing",
    "DocumentsUIGoogle": "documentsui",
    "Drive": "drive",
    "EmojiWallpaper": "emojiwallpaper",
    "GBoard": "gboard",
    "Gemini": "gemini",
    "Gmail": "gmail",
    "GmsCore": "gmscore",
    "GoogleCalculator": "calculator",
    "GoogleCalendar": "calendar",
    "GoogleCalendarSyncAdapter": "syncadapters",
    "GoogleChrome": "chrome",
    "GoogleClock": "clock",
    "GoogleContacts": "contacts",
    "GoogleContactsSyncAdapter": "syncadapters",
    "GoogleDialer": "dialer",
    "GoogleFeedback": "feedback",
    "GoogleFiles": "files",
    "GoogleKeep": "keep",
    "GoogleLocationHistory": "locationhistory",
    "GoogleMaps": "maps",
    "GoogleMessages": "messages",
    "GooglePartnerSetup": "partnersetup",
    "GooglePhotos": "photos",
    "GooglePlayStore": "vending",
    "GoogleRecorder": "recorder",
    "GoogleRestore": "restore",
    "GoogleServicesFramework": "gsf",
    "GoogleSounds": "sounds",
    "GoogleTTS": "tts",
    "GoogleWallpaper": "wallpapers",
    "MarkupGoogle": "markup",
    "PixelLauncher": "pixellauncher",
    "PixelThemes": "pixelthemes",
    "QuickAccessWallet": "wallet",
    "SetupWizard": "setupwizard",
    "StorageManager": "storagemanager",
    "TrichromeLibrary": "trichrome",
    "Velvet": "gsa",
    "WebViewGoogle": "webview",
}

# Installer settings that share the key=value shape.
SETTINGS = {
    "PR_NUMBER", "AndroidVersion", "RELEASE_DATE", "Version", "WipeDalvikCache",
    "WipeRuntimePermissions", "ExecuteBackupRestore", "UseZipConfig",
    "OverwriteWithZipConfig", "GmsOptimization", "GenerateLogs",
}

MEMBER = re.compile(r"^>>([A-Za-z0-9_]+)=(-?\d+)$")
ENTRY = re.compile(r"^([A-Za-z0-9_]+)=(-?\d+)$")


def read(path: str) -> tuple[set[str], set[str]]:
    """Return (our package ids the config installs, enabled names we do not map)."""
    sets: dict[str, tuple[int, dict[str, int]]] = {}
    current = None
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if (m := MEMBER.match(line)) and current:
            sets[current][1][m.group(1)] = int(m.group(2))
        elif m := ENTRY.match(line):
            current = m.group(1)
            sets[current] = (int(m.group(2)), {})

    on: set[str] = set()
    off: set[str] = set()
    unmapped: set[str] = set()
    for name, (value, members) in sets.items():
        if name in SETTINGS:
            continue
        for key, v in (members.items() if members else [(name, value)]):
            if key not in NAMES:
                if v == 1:
                    unmapped.add(key)
                continue
            (on if v == 1 else off).add(NAMES[key])
    # Two NikGApps apps can share one of our packages; an explicit 0 wins.
    return on - off, unmapped
