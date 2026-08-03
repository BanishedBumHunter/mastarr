"""Schema-driven provider configuration, and the secret-handling that goes with it.

The masking behaviour here was verified against a live Sonarr 4.0.18 by writing a canary
API key, editing an unrelated field, and querying the resulting SQLite row with the WAL
applied. Two things came out of that and are pinned below:

* The *arrs redact secrets themselves — a GET returns `********`, never the real value.
* PUTting that placeholder back is a no-op: the stored secret survives.

An earlier version of that experiment grepped only `sonarr.db` and concluded the secret was
destroyed. It was in `sonarr.db-wal`. Hence the tests, so nobody has to redo the archaeology.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mastarr.adapters import SonarrAdapter, UnsupportedOperation
from mastarr.adapters.base import SECRET_PLACEHOLDER, ArrAdapter

SONARR_URL = "http://sonarr.test:8989"

# Shaped exactly like a real Sonarr download client, including the redaction the service
# applies on its own.
SABNZBD_REDACTED = {
    "id": 1,
    "name": "SABnzbd",
    "implementation": "Sabnzbd",
    "protocol": "usenet",
    "enable": True,
    "fields": [
        {"name": "host", "value": "127.0.0.1", "privacy": "normal", "type": "textbox"},
        {"name": "port", "value": 8080, "privacy": "normal", "type": "textbox"},
        {"name": "apiKey", "value": "********", "privacy": "apiKey", "type": "textbox"},
        {"name": "username", "value": None, "privacy": "userName", "type": "textbox"},
        {"name": "password", "value": None, "privacy": "password", "type": "password"},
    ],
}

# A service that does NOT redact — Mastarr's own masking has to cover this case.
CANDID_CLIENT = {
    "id": 2,
    "name": "Candid",
    "implementation": "Deluge",
    "fields": [
        {"name": "host", "value": "10.0.0.5", "privacy": "normal"},
        {"name": "password", "value": "hunter2-real-secret", "privacy": "password"},
    ],
}


# ------------------------------------------------------------------ masking


def test_mastarr_masks_secrets_a_service_returned_in_the_clear():
    """Not every service redacts. Forwarding a plaintext password to a browser would
    undo the care taken with Mastarr's own credentials."""
    masked = ArrAdapter.mask_secrets(CANDID_CLIENT)
    values = {f["name"]: f["value"] for f in masked["fields"]}

    assert values["password"] == SECRET_PLACEHOLDER
    assert "hunter2-real-secret" not in str(masked)
    # Non-secret fields are untouched.
    assert values["host"] == "10.0.0.5"


def test_masking_does_not_mutate_the_original():
    original = {"fields": [{"name": "password", "value": "secret", "privacy": "password"}]}
    ArrAdapter.mask_secrets(original)
    assert original["fields"][0]["value"] == "secret"


def test_unset_secrets_stay_unset_rather_than_becoming_a_placeholder():
    """Masking an empty field would make the UI show a password where none is set."""
    masked = ArrAdapter.mask_secrets(SABNZBD_REDACTED)
    values = {f["name"]: f["value"] for f in masked["fields"]}
    assert values["username"] is None
    assert values["password"] is None


def test_restore_puts_back_a_secret_the_form_echoed():
    """The browser never sees the real value, so on save it sends the placeholder back.

    Writing that through would replace a working credential with literal asterisks — for
    any service that doesn't apply the *arrs' own unchanged-placeholder semantics.
    """
    submitted = {
        "name": "Candid renamed",
        "fields": [
            {"name": "host", "value": "10.0.0.5", "privacy": "normal"},
            {"name": "password", "value": SECRET_PLACEHOLDER, "privacy": "password"},
        ],
    }
    restored = ArrAdapter.restore_secrets(submitted, CANDID_CLIENT)
    values = {f["name"]: f["value"] for f in restored["fields"]}

    assert values["password"] == "hunter2-real-secret"
    assert restored["name"] == "Candid renamed"


def test_restore_lets_a_genuinely_new_secret_through():
    """Changing a password must actually change it."""
    submitted = {
        "fields": [{"name": "password", "value": "a-new-password", "privacy": "password"}]
    }
    restored = ArrAdapter.restore_secrets(submitted, CANDID_CLIENT)
    assert restored["fields"][0]["value"] == "a-new-password"


# ------------------------------------------------------------------- schema


@respx.mock
async def test_provider_schema_is_fetched_per_resource():
    respx.get(f"{SONARR_URL}/api/v3/downloadclient/schema").mock(
        return_value=httpx.Response(200, json=[SABNZBD_REDACTED])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        schema = await adapter.provider_schema("download_client")
    assert schema[0]["implementation"] == "Sabnzbd"


async def test_non_provider_resources_are_rejected():
    """Quality profiles have no /schema — asking for one is a programming error."""
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        with pytest.raises(UnsupportedOperation, match="not a provider type"):
            await adapter.provider_schema("quality_profile")


@pytest.mark.parametrize(
    "service_type,resource",
    [
        ("prowlarr", "import_list"),
        ("prowlarr", "metadata"),
        ("prowlarr", "quality_definition"),
        ("jellyseerr", "download_client"),
        ("jellyseerr", "notification"),
    ],
)
async def test_services_declare_the_config_they_lack(service_type, resource):
    """Verified by probing live Prowlarr 2.5 and Jellyseerr 3.3 — each of these 404s."""
    from mastarr.adapters import build_adapter

    adapter = build_adapter(service_type, "http://x:1", "key")
    try:
        with pytest.raises(UnsupportedOperation):
            await adapter.list_config(resource)
    finally:
        await adapter.aclose()


# -------------------------------------------------------------------- CRUD


@respx.mock
async def test_list_config_masks_before_returning():
    respx.get(f"{SONARR_URL}/api/v3/downloadclient").mock(
        return_value=httpx.Response(200, json=[CANDID_CLIENT])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        items = await adapter.list_config("download_client")
    assert "hunter2-real-secret" not in str(items)


@respx.mock
async def test_create_strips_the_id():
    """Sending an id from a schema template would collide with an existing record."""
    route = respx.post(f"{SONARR_URL}/api/v3/downloadclient").mock(
        return_value=httpx.Response(201, json=SABNZBD_REDACTED)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.create_provider("download_client", dict(SABNZBD_REDACTED))

    import json as _json

    assert "id" not in _json.loads(route.calls[0].request.content)


@respx.mock
async def test_update_restores_secrets_and_pins_the_id():
    respx.get(f"{SONARR_URL}/api/v3/downloadclient/2").mock(
        return_value=httpx.Response(200, json=CANDID_CLIENT)
    )
    route = respx.put(f"{SONARR_URL}/api/v3/downloadclient/2").mock(
        return_value=httpx.Response(202, json=CANDID_CLIENT)
    )
    submitted = {
        "name": "renamed",
        "fields": [{"name": "password", "value": SECRET_PLACEHOLDER, "privacy": "password"}],
    }
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.update_provider("download_client", 2, submitted)

    import json as _json

    sent = _json.loads(route.calls[0].request.content)
    assert sent["id"] == 2
    assert sent["fields"][0]["value"] == "hunter2-real-secret"


@respx.mock
async def test_test_provider_reports_failure_without_raising():
    """A failed connection test is an answer the form renders, not an error."""
    respx.post(f"{SONARR_URL}/api/v3/downloadclient/test").mock(
        return_value=httpx.Response(400)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        ok, message = await adapter.test_provider("download_client", {"name": "x"})
    assert ok is False
    assert message


@respx.mock
async def test_test_provider_reports_success():
    respx.post(f"{SONARR_URL}/api/v3/downloadclient/test").mock(
        return_value=httpx.Response(200, json={})
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        ok, _ = await adapter.test_provider("download_client", {"name": "x"})
    assert ok is True


# ------------------------------------------------------- singleton settings


NAMING = {"id": 1, "renameEpisodes": True, "standardEpisodeFormat": "{Series Title}"}


@respx.mock
async def test_singleton_update_merges_rather_than_replaces():
    """A partial PUT would blank every field Mastarr doesn't render."""
    respx.get(f"{SONARR_URL}/api/v3/config/naming").mock(
        return_value=httpx.Response(200, json=NAMING)
    )
    route = respx.put(f"{SONARR_URL}/api/v3/config/naming/1").mock(
        return_value=httpx.Response(202, json=NAMING)
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.update_singleton("naming", {"renameEpisodes": False})

    import json as _json

    sent = _json.loads(route.calls[0].request.content)
    assert sent["renameEpisodes"] is False
    assert sent["standardEpisodeFormat"] == "{Series Title}", "an unrendered field was lost"


@respx.mock
async def test_indexer_options_are_reachable():
    """This is where `minimumAge` lives — the 'don't grab it the second it appears' knob."""
    respx.get(f"{SONARR_URL}/api/v3/config/indexer").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "minimumAge": 0, "retention": 0, "rssSyncInterval": 15}
        )
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        options = await adapter.get_singleton("indexer_options")
    assert options["minimumAge"] == 0


# --------------------------------------------------- full settings coverage


@pytest.mark.parametrize(
    "resource",
    [
        "quality_definition",
        "delay_profile",
        "release_profile",
        "tag",
        "remote_path_mapping",
        "import_list_exclusion",
    ],
)
@respx.mock
async def test_every_list_resource_is_reachable(resource):
    """One generic path serves them all — a new flat list needs no new code."""
    from mastarr.adapters.base import CONFIG_ENDPOINTS_EXTRA

    endpoint = CONFIG_ENDPOINTS_EXTRA[resource]
    respx.get(f"{SONARR_URL}/api/v3/{endpoint}").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        assert await adapter.list_config(resource) == [{"id": 1}]


@pytest.mark.parametrize("group", ["download_client_options", "host", "ui"])
@respx.mock
async def test_new_settings_groups_are_reachable(group):
    from mastarr.adapters.base import SINGLETON_CONFIGS

    respx.get(f"{SONARR_URL}/api/v3/{SINGLETON_CONFIGS[group]}").mock(
        return_value=httpx.Response(200, json={"id": 1, "example": True})
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        assert (await adapter.get_singleton(group))["example"] is True


@respx.mock
async def test_quality_profile_schema_is_the_blank_template():
    """The only sane way to create a profile — quality ids are the service's vocabulary."""
    respx.get(f"{SONARR_URL}/api/v3/qualityprofile/schema").mock(
        return_value=httpx.Response(
            200, json={"name": "", "upgradeAllowed": False, "cutoff": 1, "items": [{"quality": {"id": 1, "name": "SDTV"}, "allowed": False}]}
        )
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        template = await adapter.quality_profile_schema()
    assert template["items"][0]["quality"]["name"] == "SDTV"


@pytest.mark.parametrize(
    "service_type,resource,expected",
    [
        # Verified by probing a live Prowlarr 2.5 — these 404, these do not.
        ("prowlarr", "quality_definition", False),
        ("prowlarr", "delay_profile", False),
        ("prowlarr", "remote_path_mapping", False),
        ("prowlarr", "tag", True),
        ("prowlarr", "download_client_options", True),
        ("prowlarr", "host", True),
        ("prowlarr", "ui", True),
    ],
)
def test_prowlarr_support_matches_the_live_probe(service_type, resource, expected):
    """An earlier pass wrongly marked config/downloadclient and config/host unsupported."""
    from mastarr.adapters import get_adapter_class
    from mastarr.adapters.base import CONFIG_GUARD

    cls = get_adapter_class(service_type)
    supported = CONFIG_GUARD.get(resource, resource) not in cls.unsupported
    assert supported is expected, f"{service_type}/{resource}"


@respx.mock
async def test_radarr_uses_its_own_name_for_import_list_exclusions():
    """The *arrs disagree here. Sonarr serves `importlistexclusion`; Radarr 404s on that
    and uses `exclusions`. Found only by probing both, not one."""
    from mastarr.adapters import RadarrAdapter

    radarr = respx.get("http://radarr.test:7878/api/v3/exclusions").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with RadarrAdapter("http://radarr.test:7878", "key") as adapter:
        await adapter.list_config("import_list_exclusion")
    assert radarr.called


@respx.mock
async def test_sonarr_keeps_the_standard_name():
    route = respx.get(f"{SONARR_URL}/api/v3/importlistexclusion").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with SonarrAdapter(SONARR_URL, "key") as adapter:
        await adapter.list_config("import_list_exclusion")
    assert route.called
