"""Just enough CalDAV for Nextcloud: create a calendar, list, put, delete objects."""

from __future__ import annotations

import urllib.parse

import defusedxml.ElementTree as ET
import requests

TIMEOUT = 30
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}


class CalDAVError(Exception):
    pass


class Calendar:
    def __init__(self, client: CalDAVClient, slug: str) -> None:
        self.client = client
        self.slug = slug
        self.url = f"{client.home}{slug}/"

    def objects(self) -> dict[str, str]:
        """{object file name: etag} of everything in the calendar."""
        r = self.client.request("PROPFIND", self.url, depth="1", body=(
            '<?xml version="1.0"?><d:propfind xmlns:d="DAV:">'
            "<d:prop><d:getetag/></d:prop></d:propfind>"))
        out = {}
        for resp in ET.fromstring(r.content).findall("d:response", NS):
            href = urllib.parse.unquote(resp.findtext("d:href", "", NS))
            name = href.rstrip("/").rsplit("/", 1)[-1]
            if name.endswith(".ics"):
                out[name] = resp.findtext(".//d:getetag", "", NS)
        return out

    def put(self, name: str, ics: str) -> None:
        self.client.request("PUT", self.url + name, body=ics.encode(),
                            headers={"Content-Type": "text/calendar; charset=utf-8"})

    def delete(self, name: str) -> None:
        self.client.request("DELETE", self.url + name, ok=(200, 204, 404))


class CalDAVClient:
    def __init__(self, url: str, user: str, password: str, user_agent: str) -> None:
        self.home = f"{url.rstrip('/')}/remote.php/dav/calendars/{urllib.parse.quote(user)}/"
        self.session = requests.Session()
        self.session.auth = (user, password)
        # Cloudflare in front of Nextcloud blocks some default user agents.
        self.session.headers["User-Agent"] = user_agent

    def request(self, method: str, url: str, body=None, depth: str | None = None,
                headers: dict | None = None, ok=(200, 201, 204, 207)) -> requests.Response:
        h = dict(headers or {})
        if depth is not None:
            h["Depth"] = depth
        if isinstance(body, str):
            body = body.encode()
            h.setdefault("Content-Type", "application/xml; charset=utf-8")
        r = self.session.request(method, url, data=body, headers=h, timeout=TIMEOUT)
        if r.status_code not in ok:
            raise CalDAVError(f"{method} {url.split('/remote.php')[-1]}: HTTP {r.status_code}")
        return r

    def calendars(self) -> dict[str, str]:
        """{slug: display name} of the user's calendars."""
        r = self.request("PROPFIND", self.home, depth="1", body=(
            '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
            "<d:displayname/><d:resourcetype/></d:prop></d:propfind>"))
        out = {}
        for resp in ET.fromstring(r.content).findall("d:response", NS):
            if resp.find(".//c:calendar", NS) is None:
                continue
            slug = urllib.parse.unquote(resp.findtext("d:href", "", NS)).rstrip("/").rsplit("/", 1)[-1]
            out[slug] = resp.findtext(".//d:displayname", "", NS)
        return out

    def ensure(self, slug: str, name: str, component: str, color: str) -> Calendar:
        """The calendar `slug`, created with `name` and `component` (VEVENT/VTODO) if missing."""
        if slug not in self.calendars():
            self.request("MKCALENDAR", f"{self.home}{slug}/", body=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
                'xmlns:a="http://apple.com/ns/ical/"><d:set><d:prop>'
                f"<d:displayname>{name}</d:displayname>"
                f"<a:calendar-color>{color}</a:calendar-color>"
                "<c:supported-calendar-component-set>"
                f'<c:comp name="{component}"/>'
                "</c:supported-calendar-component-set>"
                "</d:prop></d:set></c:mkcalendar>"), ok=(201,))
        return Calendar(self, slug)
