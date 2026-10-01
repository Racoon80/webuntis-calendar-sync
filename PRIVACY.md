# Privacy policy — webuntis-calendar-sync

webuntis-calendar-sync is open-source software that **you run yourself** (as a Docker
container on your own machine). There is no service, server or company behind it that
receives your data.

## What the software accesses

- **WebUntis:** your timetable, exams and homework, read with the WebUntis login you
  configure. It never changes anything in WebUntis.
- **Google (only if you use the Google target):**
  - `calendar.app.created` — create calendars and manage the events **in the calendars
    this app created**. It cannot see or change any other calendar of your account.
  - `tasks` — create and update the task list for homework.
- **Nextcloud / CalDAV (if configured):** only the three calendars the software creates
  (or the ones you point it to).

## Where your data goes

Only between WebUntis and the calendar targets **you** configure, directly from the
machine that runs the container. Nothing is sent to the author or any third party. There
is no telemetry, no analytics and no logging to external services.

## What is stored

On your machine, in the container's `data/` folder: a list of synced entries (file names,
dates and checksums — no content), and, for Google, an OAuth refresh token
(`google-token.json`). Your secrets are in the `.env` file you create.

## Revoking access

- Google: [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
- Nextcloud / CalDAV: delete the app password in your account settings
- Delete the `data/` folder to remove everything stored locally.

## Contact

Open an issue at <https://github.com/Racoon80/webuntis-calendar-sync/issues>.
