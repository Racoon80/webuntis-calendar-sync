# webuntis-calendar-sync

**Your school timetable, exams and homework from WebUntis — in Nextcloud, any CalDAV calendar or Google Calendar & Tasks.**

[WebUntis](https://webuntis.com) is the school platform many schools use for
timetables, substitutions and homework. Its app is fine for a quick look, but the
data stays locked inside it. This small Docker container copies it every hour into
the calendars you already use — on your phone, in Thunderbird, on a family
dashboard, in Home Assistant…

```
                                           ┌──▶  Nextcloud          📅 📅 ✅
 ┌──────────┐  every hour  ┌──────────────┐│
 │ WebUntis │ ───────────▶ │ webuntis-    │┼──▶  any CalDAV server  📅 📅 ✅/📅
 └──────────┘ only changes │ calendar-sync││     (iCloud, Fastmail, Radicale, …)
                           └──────────────┘└──▶  Google             📅 📅 + Google Tasks ✅
```

> Formerly **webuntis-nextcloud-sync**. Existing setups keep working — see
> [Upgrading from 0.1](#upgrading-from-01).

---

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Step-by-step setup](#step-by-step-setup)
  - [Step 1 — Get the WebUntis app secret](#step-1--get-the-webuntis-app-secret)
  - [Step 2 — Find your school's server and name](#step-2--find-your-schools-server-and-name)
  - [Step 3 — Create the project folder](#step-3--create-the-project-folder)
  - [Step 4 — Set up your target(s)](#step-4--set-up-your-targets)
    - [4a — Nextcloud](#4a--nextcloud)
    - [4b — Any CalDAV server (iCloud, Fastmail, …)](#4b--any-caldav-server-icloud-fastmail-)
    - [4c — Google Calendar and Google Tasks](#4c--google-calendar-and-google-tasks)
  - [Step 5 — Write the compose file](#step-5--write-the-compose-file)
  - [Step 6 — Check everything](#step-6--check-everything)
  - [Step 7 — Start it](#step-7--start-it)
  - [Step 8 — See it on your devices](#step-8--see-it-on-your-devices)
- [Configuration reference](#configuration-reference)
- [Commands](#commands)
- [Everyday operation](#everyday-operation)
- [Upgrading from 0.1](#upgrading-from-01)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [FAQ](#faq)
- [Development](#development)
- [License](#license)

---

## What you get

Three calendars in every target you choose:

| Calendar (name in `lb` / `de` / `fr` / `en`) | Contents |
|---|---|
| **Stonneplang** / Stundenplan / Horaire / Timetable | every lesson from last week to 4 weeks ahead: subject, room, teacher, class |
| **Prüfungen** / Prüfungen / Examens / Exams | exams up to 4 months ahead |
| **Hausaufgaben** / Hausaufgaben / Devoirs / Homework | homework with its due date — as **tasks** (Nextcloud, CalDAV, Google Tasks) or as all-day **events** |

Changes are easy to spot:

- a **cancelled** lesson becomes `❌ Fält aus: Math` / `❌ Cancelled: Math` (marked cancelled; in Google: grey and "free")
- a **changed** lesson (substitution, other room…) becomes `🔄 Math (Ännerung)` (orange in Google)
- an **exam** becomes `📝 Prüfung: Math`
- **homework** is `Math: Exercises p. 42`, with the full text and the date it was given in the notes

Titles come in **Luxembourgish** (default), **German**, **French** or **English**.
You can sync to **several targets at once**, e.g. the student's Nextcloud and the
parents' Google calendar.

## How it works

1. **Login with the app secret.** WebUntis can show a *secret* for mobile apps in your
   profile. The container turns it into a one-time code at every login, exactly like
   the Untis Mobile app. This also works for accounts that use a single sign-on
   (e.g. Luxembourg's IAM / education.lu, Office 365) — your real password is never
   needed.
2. **Timetable** comes from the official, documented WebUntis JSON-RPC API;
   **homework and exams** from the routes the WebUntis web app itself uses.
3. **Only changes are written.** An entry is written once, and then only again when
   it changes in WebUntis. If someone ticks off a homework task or deletes an entry
   on the calendar side, that stays — until WebUntis changes that entry.
4. **Removed in WebUntis → removed in the calendar**, inside the synced window. Older
   entries stay, so the calendars become a history.
5. **Only its own calendars are touched.** On Google, the login can't even *see*
   your other calendars (see [Security](#security)).
6. **No reminders, no notifications.** No entry ever carries an alarm, and nothing
   makes Nextcloud or Google send push or e-mail notifications. If you want
   reminders, let an automation read the calendars.

## Requirements

- A **WebUntis account** (student, parent or teacher) whose school allows access for
  mobile apps — almost all do.
- At least one **target**: a Nextcloud, any CalDAV account, or a Google account.
- **Docker** with the Compose plugin, on a machine that can reach WebUntis and your
  target(s). Images for `amd64` and `arm64`.

---

## Step-by-step setup

### Step 1 — Get the WebUntis app secret

1. Log in to WebUntis **in a browser**, as you always do (school login or SSO button).
2. Click your **name / profile** at the bottom left.
3. Open the tab **Freigaben** (German UI) / **Data access** / **Accès**.
4. Next to **Zugriff über Untis Mobile** / *Access via Untis Mobile*, click
   **Anzeigen** / *Display*.
5. Under the QR code is a **key** of about 16 characters — capital letters and the
   digits 2–7, e.g. `ABCDEFGH2345WXYZ`. That is **`WEBUNTIS_SECRET`**.
6. The **user name** shown there is **`WEBUNTIS_USER`**.

> [!IMPORTANT]
> The secret is **not** your password. If it looks like your password, you copied the
> wrong thing. If the tab doesn't exist, ask your school's WebUntis administrator.

### Step 2 — Find your school's server and name

From the address bar while you're logged in:

```
https://myschool.webuntis.com/WebUntis/?school=myschool#/…
        └─── WEBUNTIS_SERVER ───┘              └ WEBUNTIS_SCHOOL ┘
```

### Step 3 — Create the project folder

```sh
mkdir -p ~/webuntis-calendar-sync/data
cd ~/webuntis-calendar-sync
sudo chown 1000:1000 data          # the container runs as uid 1000
touch .env && chmod 600 .env       # all secrets go in here
```

Add the WebUntis part to `.env`:

```sh
WEBUNTIS_USER=the-user-name-from-step-1
WEBUNTIS_SECRET=ABCDEFGH2345WXYZ
```

### Step 4 — Set up your target(s)

Do one or more of 4a, 4b, 4c. Each adds a word to `TARGETS` in step 5.

#### 4a — Nextcloud

1. **Find the user ID.** With a single sign-on it is *not* the login name (it can look
   like `Authentik-1a2b3c…`). Log in as that user → **Calendar** → **Calendar
   settings** (⚙) → **Copy primary CalDAV address**:

   ```
   https://cloud.example.com/remote.php/dav/principals/users/Authentik-1a2b3c4d.../
                                                             └─ NEXTCLOUD_USER ─┘
   ```

   Admins can also use `occ user:list`.
2. **Create an app password.** As the user: *Settings → Security → Devices & sessions
   → App name* `webuntis-calendar-sync` → **Create new app password**.
   As an admin, for someone else (e.g. your child), without their password:

   ```sh
   occ user:auth-tokens:add --name webuntis-calendar-sync <user ID>
   ```

   (Nextcloud AIO: `docker exec -u www-data nextcloud-aio-nextcloud php occ …`)
3. Add to `.env`:

   ```sh
   NEXTCLOUD_USER=Authentik-1a2b3c4d...
   NEXTCLOUD_APP_PASSWORD=the-app-password
   ```

   and in step 5: `TARGETS: nextcloud` and `NEXTCLOUD_URL: https://cloud.example.com`.

Homework becomes a task list. Set `NEXTCLOUD_HOMEWORK_AS: events` if you prefer events.

#### 4b — Any CalDAV server (iCloud, Fastmail, …)

You need the server address, a user name and a password — use an **app-specific
password** wherever the provider has them.

| Provider | `CALDAV_URL` | Password | Homework |
|---|---|---|---|
| **iCloud** | `https://caldav.icloud.com/` | app-specific password from [account.apple.com](https://account.apple.com) → *Sign-In and Security* | set `CALDAV_HOMEWORK_AS: events` — iCloud no longer offers tasks over CalDAV |
| **Fastmail** | `https://caldav.fastmail.com/` | app password (*Settings → Privacy & Security*) | tasks |
| **mailbox.org** | `https://dav.mailbox.org/` | account or app password | tasks |
| **Radicale, Baïkal, SOGo, Synology…** | the server's base URL | your password | tasks |

The container finds your calendars by itself (`/.well-known/caldav` →
principal → calendar home) and creates the three calendars.

> Tested with Nextcloud and Radicale. The other providers follow the same standard
> and should work — if one doesn't, please open an issue with the log line.

The Google target is tested with the test suite and with a real Google account
(167 lessons, 5 exams, 12 homework tasks; second run writes nothing; no reminders;
the app cannot list the account's other calendars).

Add to `.env`:

```sh
CALDAV_USER=you@example.com
CALDAV_PASSWORD=the-app-specific-password
```

and in step 5: `TARGETS: caldav` (or `nextcloud,caldav`), `CALDAV_URL: …`.

**Using calendars you created yourself** — some servers don't let apps create
calendars (you'll get `the server refused to create the calendar`). Create them in
the provider's app and give their URLs:

```yaml
CALDAV_CALENDAR_URL_LESSONS: https://…/calendars/…/school/
CALDAV_CALENDAR_URL_EXAMS: https://…/calendars/…/exams/
CALDAV_CALENDAR_URL_HOMEWORK: https://…/calendars/…/homework/
```

#### 4c — Google Calendar and Google Tasks

Google needs a one-time setup of your own (free) OAuth client. It takes about
10 minutes and has to be done only once.

**1. Create a Google Cloud project**

1. Open [console.cloud.google.com](https://console.cloud.google.com/) with the Google
   account that should get the calendars.
2. Top bar → project selector → **New project** → name it `webuntis-calendar-sync` →
   **Create**, and select it.

**2. Turn on the two APIs**

*APIs & Services → Library* → search and **Enable**:
- **Google Calendar API**
- **Google Tasks API** (only needed if homework should go to Google Tasks)

**3. Configure the consent screen**

*APIs & Services → OAuth consent screen* (newer consoles: *Google Auth Platform*):

1. **User type: External** → Create.
2. App name `webuntis-calendar-sync`, your e-mail as support and developer contact →
   Save.
3. **Data access / Scopes:** add
   `…/auth/calendar.app.created` and `…/auth/tasks` → Save.
4. **Audience / Publishing status → Publish app** (to *In production*).

> [!IMPORTANT]
> **Publish the app.** While it is in *Testing*, Google lets the login expire after
> **7 days** and the sync stops. Publishing for your own use doesn't need a review —
> Google only shows an *"app isn't verified"* warning during the login, which you can
> click through (*Advanced → Go to webuntis-calendar-sync*), because it's your own app.

**4. Create the OAuth client**

*APIs & Services → Credentials → Create credentials → OAuth client ID*:
- Application type: **Desktop app**
- Name: `webuntis-calendar-sync` → **Create**

Copy the **Client ID** and **Client secret** into `.env`:

```sh
GOOGLE_CLIENT_ID=1234567890-abc….apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-…
```

and in step 5: `TARGETS: google` (or e.g. `nextcloud,google`).

**5. Log in once** — after step 5 (compose file) is done:

```sh
docker compose run --rm webuntis-calendar-sync google-login
```

1. Open the printed link in any browser, choose the Google account, allow access.
2. The browser then goes to `http://127.0.0.1:8765/?code=…` and shows *"This site can't
   be reached"* — that's expected. **Copy the whole address from the address bar**
   (not the error text) — it starts with `http://127.0.0.1:8765/?`.
3. Paste it into the terminal. Done: the login is stored in `data/google-token.json`.

Homework goes to a Google Tasks list (*Google Calendar → Tasks*, the Tasks app, Gmail
side panel). Set `GOOGLE_HOMEWORK_AS: events` to get an all-day event per homework
instead.

### Step 5 — Write the compose file

`docker-compose.yml` — keep only the lines for your targets:

```yaml
services:
  webuntis-calendar-sync:
    image: ghcr.io/racoon80/webuntis-calendar-sync:latest
    container_name: webuntis-calendar-sync
    restart: unless-stopped
    env_file: .env
    environment:
      WEBUNTIS_SERVER: myschool.webuntis.com      # step 2
      WEBUNTIS_SCHOOL: myschool                   # step 2
      TARGETS: nextcloud,caldav,google            # what you set up in step 4
      NEXTCLOUD_URL: https://cloud.example.com    # 4a
      CALDAV_URL: https://caldav.icloud.com/      # 4b
      CALDAV_HOMEWORK_AS: events                  # 4b, iCloud only
      LANGUAGE_TITLES: lb                         # lb, de, fr or en
      SYNC_INTERVAL: 3600                         # once an hour
      TZ: Europe/Luxembourg                       # the school's time zone
    volumes:
      - ./data:/data
```

### Step 6 — Check everything

Logs in to WebUntis and every target and **changes nothing**:

```sh
docker compose run --rm webuntis-calendar-sync check
```

```
WebUntis login ok
  lessons next 7 days: 38
  homework next 14 days: 4
  exams next 60 days: 1
nextcloud: login ok, 1 calendars
  Stonneplang (VEVENT): will be created
  Prüfungen (VEVENT): will be created
  Hausaufgaben (VTODO): will be created
google: login ok (token refreshed)
  calendars and the task list are created on the first sync
```

### Step 7 — Start it

```sh
docker compose up -d
docker logs -f webuntis-calendar-sync
```

```
INFO syncing every 3600s
INFO WebUntis: 167 lessons, 12 homework, 1 exams
INFO nextcloud lessons: {'written': 167, 'deleted': 0, 'unchanged': 0}
INFO nextcloud exams: {'written': 1, 'deleted': 0, 'unchanged': 0}
INFO nextcloud homework: {'written': 12, 'deleted': 0, 'unchanged': 0}
INFO google lessons: {'written': 167, 'deleted': 0, 'unchanged': 0}
…
```

From the second run on, `unchanged` is the big number.

### Step 8 — See it on your devices

- **Nextcloud:** *Calendar* and *Tasks* apps.
- **iPhone / iPad:** if the Nextcloud/CalDAV account is set up in *Settings →
  Calendar → Accounts*, the calendars (and the homework list, in *Reminders*) appear
  within minutes. For Google, add the Google account there.
- **Android:** Google calendars appear in Google Calendar by themselves; for
  Nextcloud/CalDAV use [DAVx⁵](https://www.davx5.com) and tick the new collections.
- **Parents:** share the calendars read-only with your own account, or simply add
  `google` as a second target with your own Google account.

**Done** — everything updates by itself every hour.

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `WEBUNTIS_SERVER` | — | **Required.** e.g. `myschool.webuntis.com` |
| `WEBUNTIS_SCHOOL` | — | **Required.** School login name (`school=` in the URL) |
| `WEBUNTIS_USER` / `WEBUNTIS_SECRET` | — | **Required.** User name and app secret |
| `TARGETS` | `nextcloud` if `NEXTCLOUD_URL` is set | Comma-separated: `nextcloud`, `caldav`, `google` |
| `NEXTCLOUD_URL` / `NEXTCLOUD_USER` / `NEXTCLOUD_APP_PASSWORD` | — | Nextcloud target (4a) |
| `NEXTCLOUD_HOMEWORK_AS` | `tasks` | `tasks` or `events` |
| `CALDAV_URL` / `CALDAV_USER` / `CALDAV_PASSWORD` | — | CalDAV target (4b) |
| `CALDAV_HOMEWORK_AS` | `tasks` | `tasks` or `events` (`events` for iCloud) |
| `CALDAV_CALENDAR_URL_LESSONS` / `_EXAMS` / `_HOMEWORK` | — | Use existing calendars instead of creating them |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | Google target (4c) |
| `GOOGLE_HOMEWORK_AS` | `tasks` | `tasks` (Google Tasks) or `events` |
| `LANGUAGE_TITLES` | `lb` | `lb`, `de`, `fr`, `en` — titles and calendar names |
| `CALENDAR_LESSONS` / `CALENDAR_EXAMS` / `CALENDAR_HOMEWORK` | per language | Calendar names (used when they're created) |
| `SYNC_INTERVAL` | `3600` | Seconds between syncs |
| `LESSON_DAYS` / `HOMEWORK_DAYS` / `EXAM_DAYS` | `28` / `42` / `120` | Days ahead |
| `TZ` | `Europe/Luxembourg` | The school's time zone |
| `STATE_DIR` | `/data` | Sync state and the Google login |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Commands

`docker compose run --rm webuntis-calendar-sync <command>` (or `docker exec -it …`):

| Command | What it does |
|---|---|
| `run` | Sync every `SYNC_INTERVAL` seconds (default) |
| `sync` | One sync now |
| `check` | Log in everywhere and show what would happen; changes nothing |
| `google-login` | One-time Google login (step 4c.5) |
| `health` | Exit 0 if the last sync succeeded recently (Docker health check) |

## Everyday operation

```sh
docker ps --filter name=webuntis-calendar-sync   # (healthy)?
docker logs --tail 30 webuntis-calendar-sync
cat data/status.json                             # last attempt/success, counts per target
```

- **Update:** `docker compose pull && docker compose up -d`.
- **One target broken?** The others keep syncing; the health check turns unhealthy
  and the log names the target.
- **Deleted a calendar by mistake?** The next sync creates it again and refills it.
- **New school year / other student:** stop, delete `data/state.json`, update `.env`,
  start. Old entries stay in the calendars.

## Upgrading from 0.1

Version 0.1 was called **webuntis-nextcloud-sync** and only knew Nextcloud.

1. Change the image to `ghcr.io/racoon80/webuntis-calendar-sync:latest`.
2. That's it — without `TARGETS`, a set `NEXTCLOUD_URL` means `TARGETS=nextcloud`,
   the calendars are the same, and the old `data/state.json` is converted on the
   first run **without rewriting a single entry**.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `getUserData2017: … bad credentials` | Wrong `WEBUNTIS_USER` / `WEBUNTIS_SECRET` (step 1). The secret is ~16 characters A–Z and 2–7, **not** the password. |
| `Non-base32 digit found` / `Incorrect padding` | Typo in the secret. |
| WebUntis login fails now and then | The one-time code depends on the clock: check the host's time / NTP. |
| Nextcloud `HTTP 401` | `NEXTCLOUD_USER` must be the **user ID** (4a.1), plus a valid app password. |
| `HTTP 403` from Nextcloud/CalDAV | Often a proxy/WAF (e.g. Cloudflare) blocking the request; allow `/remote.php/dav/` or use the internal URL. |
| `no CalDAV principal found` | Wrong `CALDAV_URL`, user or password. Try the provider's documented CalDAV URL. |
| `the server refused to create the calendar` | Create the calendars yourself and set `CALDAV_CALENDAR_URL_*` (4b). |
| Homework missing on iCloud | Set `CALDAV_HOMEWORK_AS: events`. |
| `not logged in to Google` | Run `google-login` (4c.5). |
| `Error 400: redirect_uri_mismatch` during the Google login | The OAuth client is not of type **Desktop app**. Create a new one (4c.4). |
| `Error 403: access_denied` — *app is being tested* | The app is still in *Testing*: publish it (4c.3), or add your account as a test user. |
| *"Publish app"* is greyed out | Fill in the app home page and privacy policy link on the **Branding** page first (the repo URL and its `PRIVACY.md` work for personal use). |
| `Google token refresh failed: invalid_grant` | The login expired or was revoked. If it happens weekly, the app is still in *Testing* — publish it (4c.3), then `google-login` again. |
| Google `HTTP 403 … has not been used in project … or it is disabled` | Enable the Calendar / Tasks API (4c.2). |
| `PermissionError … /data/…` | `sudo chown -R 1000:1000 data` |
| Lessons one or two hours off | Set `TZ` to the school's time zone. |

## Security

- **Secrets** (WebUntis secret, Nextcloud/CalDAV passwords, Google client secret) live
  only in `.env`. The Google login is `data/google-token.json` (mode 600).
  `data/state.json` holds file names, dates and checksums — no content, no credentials.
- **Google permissions are minimal:** `calendar.app.created` lets the app create
  calendars and manage *only those*; it can't see or change your other calendars.
  `tasks` is for the homework list. Revoke anytime at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- **Nextcloud/CalDAV:** use app passwords; revoke them in the provider's settings.
- **WebUntis** is only read. On the calendar side, only the container's own
  calendars are written.
- No telemetry, no other servers: it only talks to WebUntis and your targets.

## FAQ

**Is this official?**
No. The timetable uses the official, documented WebUntis JSON-RPC API that the school
has to allow; homework and exams use the same routes as the WebUntis web app. Not
affiliated with Untis GmbH, Nextcloud GmbH, Apple or Google. It may break if Untis
changes things.

**Does it work with Office 365 / IAM / iServ login?**
Yes — that's why it uses the app secret. Tested with Luxembourg's IAM (education.lu).

**Several children?** One container per child (own folder, own `.env`).

**Why does Google need my own "app"?** Google only hands out access to calendars to
registered OAuth clients. Using your own client means nobody else is involved and
nobody else's quota or review applies.

**Notifications at 6:40 with today's timetable?** Not built in, on purpose — and the
calendars never trigger reminders. An automation (Home Assistant, n8n, …) can read
the calendars and send whatever you like.

## Development

```sh
git clone https://github.com/Racoon80/webuntis-calendar-sync
cd webuntis-calendar-sync
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest -q                      # CalDAV against a throw-away Radicale, Google against a fake
```

```
webuntis_calendar_sync/
  untis.py     WebUntis login (app secret → one-time code), timetable, homework, exams
  ics.py       titles/descriptions (lb/de/fr/en) and iCalendar events/tasks
  caldav.py    minimal CalDAV client with discovery
  google.py    Google OAuth + Calendar/Tasks REST
  targets.py   Nextcloud / CalDAV / Google targets
  __main__.py  sync logic (write only changes, delete what vanished), commands
```

Pushes to `main` run the tests and publish the multi-arch image to
`ghcr.io/racoon80/webuntis-calendar-sync`; tags `v*` publish versioned images.

## License

[MIT](LICENSE). Not affiliated with Untis GmbH, Nextcloud GmbH, Apple or Google. See also the [privacy policy](PRIVACY.md).
