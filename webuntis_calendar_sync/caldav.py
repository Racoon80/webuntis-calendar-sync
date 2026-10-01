"""Just enough CalDAV: find the calendar home, create a calendar, put and delete objects.

Works with Nextcloud, and with any CalDAV server that supports the usual discovery
(RFC 6764 /.well-known/caldav → current-user-principal → calendar-home-set):
Radicale, Baïkal, SOGo, Fastmail, mailbox.org, iCloud, Synology, …
"""

from __future__ import annotations

import urllib.parse
from xml.sax.saxutils import escape

import defusedxml.ElementTree as ET
import requests

TIMEOUT = 30
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}


class CalDAVError(Exception):
    pass


class Calendar:
    def __init__(self, client: CalDAVClient, url: str) -> None:
        self.client = client
        self.url = url if url.endswith("/") else url + "/"

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
        self.client.request("DELETE", self.url + name, ok=(200, 204, 404, 410))


class CalDAVClient:
    def __init__(self, home: str, user: str, password: str, user_agent: str) -> None:
        """`home` is the calendar home collection, e.g. …/remote.php/dav/calendars/<user>/."""
        self.home = home if home.endswith("/") else home + "/"
        self.session = requests.Session()
        self.session.auth = (user, password)
        # Some proxies in front of CalDAV servers (e.g. Cloudflare) block default user agents.
        self.session.headers["User-Agent"] = user_agent

    @classmethod
    def nextcloud(cls, url: str, user: str, password: str, user_agent: str) -> CalDAVClient:
        home = f"{url.rstrip('/')}/remote.php/dav/calendars/{urllib.parse.quote(user)}/"
        return cls(home, user, password, user_agent)

    @classmethod
    def discover(cls, url: str, user: str, password: str, user_agent: str) -> CalDAVClient:
        """Find the calendar home from a server URL (RFC 6764 / RFC 4791)."""
        probe = cls(url, user, password, user_agent)
        parsed = urllib.parse.urlparse(url)
        candidates = [url]
        if parsed.path in ("", "/"):
            candidates.insert(0, f"{parsed.scheme}://{parsed.netloc}/.well-known/caldav")
        principal = None
        for candidate in candidates:
            try:
                r, final = probe._propfind_follow(candidate, "<d:current-user-principal/>")
            except CalDAVError:
                continue
            href = ET.fromstring(r.content).findtext(".//d:current-user-principal/d:href", "", NS)
            if href:
                principal = urllib.parse.urljoin(final, href)
                break
        if not principal:
            raise CalDAVError(f"no CalDAV principal found at {url}")
        r, final = probe._propfind_follow(principal, "<c:calendar-home-set/>")
        href = ET.fromstring(r.content).findtext(".//c:calendar-home-set/d:href", "", NS)
        if not href:
            raise CalDAVError("the server did not report a calendar-home-set")
        return cls(urllib.parse.urljoin(final, href), user, password, user_agent)

    def _propfind_follow(self, url: str, prop: str, hops: int = 5):
        """PROPFIND depth 0, following redirects without turning them into GETs."""
        body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" '
                f'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>{prop}</d:prop></d:propfind>')
        for _ in range(hops):
            r = self.session.request("PROPFIND", url, data=body.encode(), allow_redirects=False,
                                     headers={"Depth": "0",
                                              "Content-Type": "application/xml; charset=utf-8"},
                                     timeout=TIMEOUT)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                url = urllib.parse.urljoin(url, r.headers["Location"])
                continue
            if r.status_code != 207:
                raise CalDAVError(f"PROPFIND {url}: HTTP {r.status_code}")
            return r, url
        raise CalDAVError(f"too many redirects from {url}")

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
            path = urllib.parse.urlparse(url).path
            raise CalDAVError(f"{method} {path}: HTTP {r.status_code}")
        return r

    def calendars(self) -> dict[str, str]:
        """{slug: display name} of the calendars in the home collection."""
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

    def ensure(self, slug: str, name: str, component: str, color: str) -> tuple[Calendar, bool]:
        """(calendar `slug`, created?) — created with `name` and `component` if missing."""
        url = f"{self.home}{slug}/"
        if slug in self.calendars():
            return Calendar(self, url), False
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
                'xmlns:a="http://apple.com/ns/ical/"><d:set><d:prop>'
                f"<d:displayname>{escape(name)}</d:displayname>"
                f"<a:calendar-color>{color}</a:calendar-color>"
                "<c:supported-calendar-component-set>"
                f'<c:comp name="{component}"/>'
                "</c:supported-calendar-component-set>"
                "</d:prop></d:set></c:mkcalendar>")
        r = self.request("MKCALENDAR", url, body=body, ok=(201, 403, 405))
        if r.status_code != 201:
            raise CalDAVError(
                f"the server refused to create the calendar '{name}' (HTTP {r.status_code}); "
                "create it yourself and set its URL (see README: existing calendars)")
        return Calendar(self, url), True
