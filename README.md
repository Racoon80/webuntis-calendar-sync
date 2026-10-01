# webuntis-nextcloud-sync

**Your school timetable, exams and homework from WebUntis — as calendars and tasks in your own Nextcloud.**

[WebUntis](https://webuntis.com) is the school platform many schools use for
timetables, substitutions and homework. Its app is fine for a quick look, but the
data stays locked inside it. This small Docker container copies it into
[Nextcloud](https://nextcloud.com) every hour, so it shows up wherever your
Nextcloud calendars already are: the iPhone/Android calendar, Thunderbird, the
Nextcloud Calendar and Tasks apps, Home Assistant, a family dashboard…

```
 ┌──────────┐   every hour    ┌─────────────────────────┐   CalDAV    ┌──────────────────────────────┐
 │ WebUntis │ ──────────────▶ │ webuntis-nextcloud-sync │ ──────────▶ │ Nextcloud                    │
 └──────────┘  only changes   └─────────────────────────┘             │  📅 Timetable  📅 Exams       │
                                                                      │  ✅ Homework (task list)      │
                                                                      └──────────────────────────────┘
```

---

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Step-by-step setup](#step-by-step-setup)
  - [Step 1 — Get the WebUntis app secret](#step-1--get-the-webuntis-app-secret)
  - [Step 2 — Find your school's server and name](#step-2--find-your-schools-server-and-name)
  - [Step 3 — Find the Nextcloud user ID](#step-3--find-the-nextcloud-user-id)
  - [Step 4 — Create a Nextcloud app password](#step-4--create-a-nextcloud-app-password)
  - [Step 5 — Create the project folder and `.env`](#step-5--create-the-project-folder-and-env)
  - [Step 6 — Write the compose file](#step-6--write-the-compose-file)
  - [Step 7 — Check both logins](#step-7--check-both-logins)
  - [Step 8 — Start it](#step-8--start-it)
  - [Step 9 — See it in Nextcloud and on your phone](#step-9--see-it-in-nextcloud-and-on-your-phone)
- [Configuration reference](#configuration-reference)
- [Commands](#commands)
- [Everyday operation](#everyday-operation)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [FAQ](#faq)
- [Development](#development)
- [License](#license)

---

## What you get

Three new calendars in the Nextcloud account you choose (usually the student's):

| Calendar (default name in `lb` / `de` / `fr` / `en`) | Kind | Contents |
|---|---|---|
| **Stonneplang** / Stundenplan / Horaire / Timetable | events | every lesson from last week to 4 weeks ahead, with subject, room, teacher, class |
| **Prüfungen** / Prüfungen / Examens / Exams | events | exams up to 4 months ahead |
| **Hausaufgaben** / Hausaufgaben / Devoirs / Homework | **tasks** | homework with its due date, ticked off when done in WebUntis |

Changes are easy to spot:

- a **cancelled** lesson becomes `❌ Fält aus: Math` (or `❌ Cancelled: Math`) and is marked *cancelled*
- a **changed** lesson (substitution, other room…) becomes `🔄 Math (Ännerung)`
- an **exam** becomes `📝 Prüfung: Math`
- a **homework** task is `Math: Exercises p. 42`, with the full text and the date it was given in the notes

Titles and descriptions come in **Luxembourgish** (default), **German**, **French** or **English**.

## How it works

1. **Login with the app secret.** WebUntis lets you show a *secret* for mobile apps
   in your profile. The container turns it into a one-time code every time it logs in,
   exactly like the Untis Mobile app does. This also works for accounts that log in
   through a single sign-on (e.g. Luxembourg's IAM / education.lu), which can't use
   the plain password login of the API — and your real password is never needed.
2. **Timetable** comes from the official, documented WebUntis JSON-RPC API.
   **Homework and exams** come from the routes the WebUntis web app itself uses,
   with the same session.
3. **Only changes are written.** Each entry is written to Nextcloud once and then only
   again when it changes in WebUntis. So if the student ticks off a homework task or
   deletes an entry in Nextcloud, that stays — until WebUntis changes that entry.
4. **Removed in WebUntis → removed in Nextcloud.** If a lesson disappears from
   WebUntis inside the synced window, it is deleted from the calendar too. Older
   entries outside the window are left alone, so the calendar becomes a history.
5. The container **never touches other calendars** — only the three it created
   (their internal names all start with `webuntis-`).

It **does not send notifications.** Use your calendar app's reminders, or an
automation (Home Assistant, n8n, …) that reads the calendars.

## Requirements

- A **WebUntis account** (student or parent/teacher account that can see a timetable).
  Your school must allow access for mobile apps — almost all do.
- A **Nextcloud** with the *Calendar* app (and the *Tasks* app if you want to tick
  off homework in the browser).
- **Docker** with the Compose plugin, on a machine that can reach both
  `*.webuntis.com` and your Nextcloud. Images exist for `amd64` and `arm64`.

---

## Step-by-step setup

### Step 1 — Get the WebUntis app secret

1. Log in to WebUntis **in a browser** (not the app), like you always do — with the
   school's own login or with the SSO button.
2. Click your **name / profile** at the bottom left.
3. Open the tab **Freigaben** (German UI) / **Data access** / **Accès**.
4. Next to **Zugriff über Untis Mobile** / *Access via Untis Mobile*, click
   **Anzeigen** / *Display*.
5. You see a QR code, and underneath it a **key** of about 16 characters, made of
   capital letters and the digits 2–7, e.g. `ABCDEFGH2345WXYZ`.
   That is your **`WEBUNTIS_SECRET`**.
6. Also note the **user name** shown there. That is your **`WEBUNTIS_USER`**.

> [!IMPORTANT]
> The secret is **not** your password. If it looks like your password, you copied the
> wrong thing. If the tab doesn't exist, your school has switched mobile access off;
> ask the school's WebUntis administrator.

### Step 2 — Find your school's server and name

Look at the address bar while you're logged in:

```
https://myschool.webuntis.com/WebUntis/?school=myschool#/…
        └─── WEBUNTIS_SERVER ───┘              └ WEBUNTIS_SCHOOL ┘
```

- `WEBUNTIS_SERVER` is the host name, e.g. `myschool.webuntis.com` or `neilo.webuntis.com`.
- `WEBUNTIS_SCHOOL` is the school's **login name** — the `school=` part. It's often,
  but not always, the same as the start of the server name.

### Step 3 — Find the Nextcloud user ID

The calendars are created in one Nextcloud account. For CalDAV you need that
account's **user ID**, which is **not always the name you log in with** — with a
single sign-on (Authentik, Keycloak, Azure…) it can look like
`Authentik-1a2b3c…` or a UUID.

The easy way:

1. Log in to Nextcloud **as that user** and open the **Calendar** app.
2. Bottom left: **Calendar settings** (⚙).
3. Click **Copy primary CalDAV address**. You get something like

   ```
   https://cloud.example.com/remote.php/dav/principals/users/Authentik-1a2b3c4d5e6f.../
                                                             └──── NEXTCLOUD_USER ────┘
   ```

   The part after `/users/` is the **`NEXTCLOUD_USER`**.

If you are the Nextcloud admin, this also works:

```sh
occ user:list          # "user ID: display name"
```

### Step 4 — Create a Nextcloud app password

Don't use the real password; give the container its own app password, which you
can revoke at any time.

**As the user:** *Settings → Security → Devices & sessions → App name*
`webuntis-nextcloud-sync` → **Create new app password**. Copy the password shown.
That is **`NEXTCLOUD_APP_PASSWORD`**.

**As the admin, for someone else's account** (e.g. your child's), without knowing
their password:

```sh
occ user:auth-tokens:add --name webuntis-nextcloud-sync <user ID from step 3>
```

The password is printed on the last line. The user sees it under *Devices & sessions*
and can revoke it there.

> On Nextcloud AIO the command is
> `docker exec -u www-data nextcloud-aio-nextcloud php occ …`.

### Step 5 — Create the project folder and `.env`

```sh
mkdir -p ~/webuntis-nextcloud-sync/data
cd ~/webuntis-nextcloud-sync
sudo chown 1000:1000 data          # the container runs as uid 1000
```

Put the four secrets into `.env`:

```sh
cat > .env <<'EOF'
WEBUNTIS_USER=the-user-name-from-step-1
WEBUNTIS_SECRET=ABCDEFGH2345WXYZ
NEXTCLOUD_USER=the-user-id-from-step-3
NEXTCLOUD_APP_PASSWORD=the-app-password-from-step-4
EOF
chmod 600 .env
```

### Step 6 — Write the compose file

`docker-compose.yml`:

```yaml
services:
  webuntis-nextcloud-sync:
    image: ghcr.io/racoon80/webuntis-nextcloud-sync:latest
    container_name: webuntis-nextcloud-sync
    restart: unless-stopped
    env_file: .env
    environment:
      WEBUNTIS_SERVER: myschool.webuntis.com     # step 2
      WEBUNTIS_SCHOOL: myschool                  # step 2
      NEXTCLOUD_URL: https://cloud.example.com   # your Nextcloud, without /remote.php
      LANGUAGE_TITLES: lb                        # lb, de, fr or en
      SYNC_INTERVAL: 3600                        # once an hour
      TZ: Europe/Luxembourg                      # the school's time zone
    volumes:
      - ./data:/data
```

### Step 7 — Check both logins

This logs in to WebUntis and Nextcloud and **changes nothing**:

```sh
docker compose run --rm webuntis-nextcloud-sync check
```

```
WebUntis login ok
  lessons next 7 days: 38
  homework next 14 days: 4
  exams next 60 days: 0
Nextcloud login ok, 1 calendars
  Stonneplang: will be created
  Prüfungen: will be created
  Hausaufgaben: will be created
```

If a login fails, see [Troubleshooting](#troubleshooting) before going on.

### Step 8 — Start it

```sh
docker compose up -d
docker logs -f webuntis-nextcloud-sync
```

The first sync runs right away:

```
INFO syncing every 3600s
INFO WebUntis: 167 lessons, 12 homework, 0 exams
INFO Stonneplang: {'written': 167, 'deleted': 0, 'unchanged': 0}
INFO Prüfungen: {'written': 0, 'deleted': 0, 'unchanged': 0}
INFO Hausaufgaben: {'written': 12, 'deleted': 0, 'unchanged': 0}
```

From the second run on, `unchanged` should be the big number — only real changes in
WebUntis are written.

### Step 9 — See it in Nextcloud and on your phone

- **Nextcloud web:** the three calendars appear in *Calendar*; homework appears in
  *Tasks* (and in Calendar as tasks with a due date).
- **iPhone / iPad:** if the Nextcloud account is already added under
  *Settings → Calendar → Accounts* (CalDAV), the new calendars and the homework list
  (in *Reminders*) show up by themselves within a few minutes.
- **Android:** with [DAVx⁵](https://www.davx5.com), refresh the account and tick the
  three new collections.
- **Parents:** share the calendars from the student's Nextcloud account with yours
  (*Calendar → … → Share*), read-only.

**Done.** From now on everything updates by itself every hour.

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `WEBUNTIS_SERVER` | — | **Required.** e.g. `myschool.webuntis.com` |
| `WEBUNTIS_SCHOOL` | — | **Required.** School login name (`school=` in the URL) |
| `WEBUNTIS_USER` | — | **Required.** WebUntis user name |
| `WEBUNTIS_SECRET` | — | **Required.** App secret from *Data access* |
| `NEXTCLOUD_URL` | — | **Required.** e.g. `https://cloud.example.com` |
| `NEXTCLOUD_USER` | — | **Required.** Nextcloud **user ID** (step 3) |
| `NEXTCLOUD_APP_PASSWORD` | — | **Required.** App password for that user |
| `LANGUAGE_TITLES` | `lb` | Titles and calendar names: `lb`, `de`, `fr`, `en` |
| `CALENDAR_LESSONS` / `CALENDAR_EXAMS` / `CALENDAR_HOMEWORK` | per language | Override a calendar's display name (only used when it is created) |
| `SYNC_INTERVAL` | `3600` | Seconds between syncs |
| `LESSON_DAYS` | `28` | How many days ahead the timetable is synced |
| `HOMEWORK_DAYS` | `42` | Days ahead for homework |
| `EXAM_DAYS` | `120` | Days ahead for exams |
| `TZ` | `Europe/Luxembourg` | The school's time zone (lesson times are local times) |
| `STATE_DIR` | `/data` | Where the sync state is kept |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Commands

`docker exec webuntis-nextcloud-sync webuntis-nextcloud-sync <command>`, or
`docker compose run --rm webuntis-nextcloud-sync <command>`:

| Command | What it does |
|---|---|
| `run` | Sync every `SYNC_INTERVAL` seconds (container default) |
| `sync` | One sync now, then exit |
| `check` | Log in to both sides and print counts; changes nothing |
| `health` | Exit 0 if the last sync succeeded recently (used by the Docker health check) |

## Everyday operation

```sh
docker ps --filter name=webuntis-nextcloud-sync   # (healthy)?
docker logs --tail 20 webuntis-nextcloud-sync
cat data/status.json                              # last attempt, last success, counts
```

**Update:** `docker compose pull && docker compose up -d`.

**New school year / different student:** stop the container, delete
`data/state.json`, update `.env`, start again. Old entries stay in the calendars;
delete the calendars in Nextcloud if you want a clean start.

**Start over completely:** delete the three calendars in Nextcloud and
`data/state.json`. The next sync creates everything again.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `getUserData2017: … bad credentials` (or another login error) | Wrong `WEBUNTIS_USER` or `WEBUNTIS_SECRET`. Copy both again from *Data access* (step 1). The secret is ~16 characters, A–Z and 2–7, **not** your password. |
| `Incorrect padding` / `Non-base32 digit found` | The secret has a typo or extra characters. |
| Login worked a minute ago, now `bad credentials` | The one-time code depends on the clock. Check the host's time (`date`), NTP must be running. |
| `HTTP 401` from Nextcloud | Wrong `NEXTCLOUD_USER` (must be the **user ID**, step 3) or app password. |
| `HTTP 403` from Nextcloud | Often a proxy/WAF (e.g. Cloudflare) blocking the request. Allow the path `/remote.php/dav/` or use the internal URL of Nextcloud. |
| `HTTP 404` on `PROPFIND …/calendars/<user>/` | `NEXTCLOUD_USER` doesn't exist, or the Calendar app isn't enabled. |
| `PermissionError … /data/state.json` | `sudo chown -R 1000:1000 data` |
| No homework / exams although there are some | Your school may not use those features in WebUntis, or the account type can't see them. `check` shows what the API returns. |
| Lessons one or two hours off | Set `TZ` to the school's time zone. |

## Security

- **What's stored where:** the WebUntis secret and the Nextcloud app password are only
  in `.env`. `data/state.json` only has file names, dates and checksums — no
  timetable content, no credentials.
- **The WebUntis secret** gives read access to that WebUntis account, like the mobile
  app. Keep `.env` private (`chmod 600`) and out of Git and shared backups.
- **The Nextcloud app password** is limited to that account and can be revoked at any
  time under *Settings → Security → Devices & sessions*.
- The container only **reads** WebUntis. In Nextcloud it only writes to the three
  calendars it created.
- No telemetry, no other servers: it only talks to WebUntis and your Nextcloud.

## FAQ

**Is this official?**
No. The timetable uses the official, documented WebUntis JSON-RPC API that the school
has to allow. Homework and exams use the same routes as the WebUntis web app. It's not
affiliated with Untis GmbH; it may break if Untis changes things.

**Does it work with Office 365 / IAM / iServ login?**
Yes — that's why it uses the app secret instead of the password. It's tested with
Luxembourg's IAM (education.lu).

**Can I sync several children?**
Run one container per child (different folders, different `.env`).

**Why tasks for homework and not events?**
So they can be ticked off, and so they show up in task/reminder apps with their due
date.

**Notifications at 6:40 with today's timetable?**
Not built in on purpose. Your calendar app can remind you, or an automation can read
the calendars and send whatever you like.

## Development

```sh
git clone https://github.com/Racoon80/webuntis-nextcloud-sync
cd webuntis-nextcloud-sync
python -m venv .venv && . .venv/bin/activate
pip install -e .
set -a; . ./.env; set +a
export WEBUNTIS_SERVER=… WEBUNTIS_SCHOOL=… NEXTCLOUD_URL=… STATE_DIR=./data
webuntis-nextcloud-sync check
docker build -t webuntis-nextcloud-sync .
```

```
webuntis_nextcloud_sync/
  untis.py     WebUntis login (app secret → one-time code), timetable, homework, exams
  caldav.py    minimal CalDAV client: create calendar, list, put, delete
  ics.py       iCalendar events/tasks, titles in lb/de/fr/en
  __main__.py  sync logic (write only changes, delete what vanished), commands
```

Pushes to `main` build and publish the multi-arch image to
`ghcr.io/racoon80/webuntis-nextcloud-sync` via GitHub Actions; tags `v*` publish
versioned images.

## License

[MIT](LICENSE). Not affiliated with Untis GmbH or Nextcloud GmbH.
