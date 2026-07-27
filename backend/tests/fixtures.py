"""Recorded *arr API payloads.

Trimmed to the fields Mastarr actually reads, but the structure — including the awkward
double-nesting of `quality.quality.name` and the `records` envelope on paged endpoints —
matches what the real services return.
"""

from __future__ import annotations

SONARR_STATUS = {
    "appName": "Sonarr",
    "instanceName": "Sonarr",
    "version": "4.0.10.2544",
    "osName": "ubuntu",
    "isDocker": True,
    "startTime": "2026-07-20T09:14:22Z",
}

RADARR_STATUS = {
    "appName": "Radarr",
    "instanceName": "Radarr",
    "version": "5.14.0.9383",
    "osName": "ubuntu",
    "isDocker": True,
    "startTime": "2026-07-20T09:15:01Z",
}

PROWLARR_STATUS = {
    "appName": "Prowlarr",
    "instanceName": "Prowlarr",
    "version": "1.24.3.4754",
    "osName": "ubuntu",
    "isDocker": True,
    "startTime": "2026-07-20T09:15:44Z",
}

HEALTH_OK: list[dict] = []

HEALTH_WARNINGS = [
    {
        "source": "IndexerStatusCheck",
        "type": "warning",
        "message": "Indexers unavailable due to failures: NZBgeek",
        "wikiUrl": "https://wiki.servarr.com/sonarr/system#indexers-are-unavailable",
    },
    {
        "source": "RootFolderCheck",
        "type": "error",
        "message": "Missing root folder: /media/tv",
        "wikiUrl": "https://wiki.servarr.com/sonarr/system#missing-root-folder",
    },
]

HEALTH_NOTICE_ONLY = [
    {
        "source": "UpdateCheck",
        "type": "notice",
        "message": "New update is available",
        "wikiUrl": "",
    }
]

DISKSPACE = [
    {
        "path": "/media",
        "label": "media",
        "freeSpace": 2_000_000_000_000,
        "totalSpace": 8_000_000_000_000,
    },
    {"path": "/config", "label": "", "freeSpace": 10_000_000_000, "totalSpace": 50_000_000_000},
]

SONARR_QUEUE = {
    "page": 1,
    "pageSize": 100,
    "totalRecords": 2,
    "records": [
        {
            "id": 101,
            "title": "Some.Show.S01E02.1080p.WEB-DL",
            "status": "downloading",
            "size": 2_000_000_000,
            "sizeleft": 500_000_000,
            "downloadClient": "sabnzbd",
            "indexer": "NZBgeek",
            "estimatedCompletionTime": "2026-07-27T12:00:00Z",
            "quality": {"quality": {"id": 3, "name": "WEBDL-1080p"}},
            "series": {"id": 7, "title": "Some Show"},
            "episode": {"id": 55, "seasonNumber": 1, "episodeNumber": 2},
        },
        {
            "id": 102,
            "title": "Другое.Шоу.S02E01",
            "status": "warning",
            "size": 1_000_000_000,
            "sizeleft": 1_000_000_000,
            "downloadClient": "sabnzbd",
            "indexer": "DrunkenSlug",
            "quality": {"quality": {"id": 1, "name": "SDTV"}},
            "series": {"id": 9, "title": "Другое Шоу"},
            "episode": {"id": 90, "seasonNumber": 2, "episodeNumber": 1},
            "statusMessages": [
                {"title": "import failed", "messages": ["No files found are eligible"]}
            ],
        },
    ],
}

RADARR_QUEUE = {
    "page": 1,
    "pageSize": 100,
    "totalRecords": 1,
    "records": [
        {
            "id": 201,
            "title": "Some.Movie.2024.2160p.BluRay",
            "status": "downloading",
            "size": 40_000_000_000,
            "sizeleft": 10_000_000_000,
            "downloadClient": "qbittorrent",
            "indexer": "TorrentLeech",
            "quality": {"quality": {"id": 19, "name": "Bluray-2160p"}},
            "movie": {"id": 3, "title": "Some Movie"},
        }
    ],
}

SONARR_HISTORY = {
    "page": 1,
    "pageSize": 50,
    "totalRecords": 1,
    "records": [
        {
            "id": 900,
            "eventType": "downloadFolderImported",
            "sourceTitle": "Some.Show.S01E01.1080p.WEB-DL",
            "date": "2026-07-26T22:31:04Z",
            "quality": {"quality": {"id": 3, "name": "WEBDL-1080p"}},
            "series": {"id": 7, "title": "Some Show"},
        }
    ],
}

QUALITY_PROFILES = [
    {
        "id": 1,
        "name": "HD-1080p",
        "upgradeAllowed": True,
        "cutoff": 3,
        "items": [
            {"quality": {"id": 1, "name": "SDTV"}, "allowed": False},
            {"quality": {"id": 3, "name": "WEBDL-1080p"}, "allowed": True},
        ],
    }
]

ROOT_FOLDERS = [
    {"id": 1, "path": "/media/tv", "accessible": True, "freeSpace": 2_000_000_000_000},
    {"id": 2, "path": "/media/tv-4k", "accessible": False, "freeSpace": 0},
]

DOWNLOAD_CLIENTS = [
    {
        "id": 1,
        "name": "SABnzbd",
        "implementation": "Sabnzbd",
        "enable": True,
        "protocol": "usenet",
        "priority": 1,
    },
    {
        "id": 2,
        "name": "qBittorrent",
        "implementation": "QBittorrent",
        "enable": False,
        "protocol": "torrent",
        "priority": 1,
    },
]

INDEXERS = [
    {
        "id": 1,
        "name": "NZBgeek",
        "implementation": "Newznab",
        "enable": True,
        "protocol": "usenet",
        "priority": 25,
    }
]

# Prowlarr's indexer list uses `enabled` rather than `enable` — the kind of small dialect
# difference the base adapter has to tolerate.
PROWLARR_INDEXERS = [
    {
        "id": 4,
        "name": "1337x",
        "implementation": "Cardigann",
        "enabled": True,
        "protocol": "torrent",
        "priority": 25,
    }
]

SONARR_LOOKUP = [
    {
        "title": "Some Show",
        "year": 2019,
        "overview": "A show about things.",
        "tvdbId": 123456,
        "images": [{"coverType": "poster", "remoteUrl": "https://img/poster.jpg"}],
    },
    {
        "title": "Already Added Show",
        "year": 2021,
        "tvdbId": 654321,
        "id": 12,
        "images": [],
    },
]

RADARR_LOOKUP = [
    {
        "title": "Some Movie",
        "year": 2024,
        "overview": "A movie about things.",
        "tmdbId": 99887,
        "images": [{"coverType": "poster", "url": "/MediaCover/1/poster.jpg"}],
    }
]

PING_OK = {"status": "OK"}
