# Xtream What's New

[Français](README.fr.md)

Xtream What's New is a lightweight Docker application that monitors an Xtream-compatible VOD and series catalogue and highlights what changed since previous scans.

## Highlights

- 🎬 Detects new movies, series and episodes, plus catalogue removals and other changes.
- 🌍 Filters monitoring by country and provider categories.
- 🌓 Light and dark themes with the preferred theme remembered by the browser.
- 📧 Configurable email digests for movies, series, episodes, categories and removals.
- ⚠️ Immediate email alerts for scan and backup failures.
- 🔄 Configurable automatic scans directly from the web interface.
- 💾 Integrated scheduled SQLite backups with configurable retention.
- 🔎 Searchable history with Today, 7-day and 30-day views.
- 🧹 Cleans provider language prefixes such as `|FR|` from displayed titles without altering the stored provider data.
- 🐳 Designed for simple self-hosting with Docker Compose and GHCR images.

![Xtream What's New dashboard](docs/images/dashboard.png)


It does **not** play or proxy streams. It monitors catalogue metadata exposed by the provider API.

## Features

- Automatic discovery of provider VOD and series categories.
- Country/zone detection from category names and flags.
- Per-country and per-category monitoring selection.
- Detection of new movies, series and episodes.
- Category additions, removals and renames, plus confirmed content removals.
- Safe baseline handling when enabling a category.
- Today, 7-day and 30-day history views with 45-day event retention.
- Configurable automatic scans and manual scans.
- Built-in SQLite backups with scheduling, rotation and manual backup.
- SMTP email notifications, immediate or periodic digest.
- French and English interface and email output.
- Provider and SMTP credentials kept outside SQLite.

## Quick install — Dockhand / Portainer / Compose stack

The recommended installation uses the published Docker image:

```text
ghcr.io/slideboy/xtream-whats-new:latest
```

You do **not** need to download `watcher.py`, create application folders, or create `config.json` manually.

In Dockhand or Portainer, create a new Stack and paste the following Compose configuration:

```yaml
services:
  xtream-whats-new:
    image: ghcr.io/slideboy/xtream-whats-new:latest
    container_name: xtream-whats-new
    restart: unless-stopped

    ports:
      - "${XTREAM_WHATS_NEW_PORT:-36401}:36401"

    environment:
      XTREAM_PROVIDER_URL: "${XTREAM_PROVIDER_URL}"
      XTREAM_USERNAME: "${XTREAM_USERNAME}"
      XTREAM_PASSWORD: "${XTREAM_PASSWORD}"
      SMTP_USERNAME: "${SMTP_USERNAME:-}"
      SMTP_PASSWORD: "${SMTP_PASSWORD:-}"
      TZ: "${TZ:-Europe/Paris}"

    volumes:
      - xtream-whats-new-data:/data

    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:36401/', timeout=5)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

volumes:
  xtream-whats-new-data:
    name: xtream-whats-new-data
```

### Environment variables

Before deploying the Stack, define the following environment variables in Dockhand or Portainer:

```env
XTREAM_PROVIDER_URL=https://your-provider.example
XTREAM_USERNAME=your_username
XTREAM_PASSWORD=your_password
```

Optional variables:

```env
XTREAM_WHATS_NEW_PORT=36401
TZ=Europe/Paris
SMTP_USERNAME=
SMTP_PASSWORD=
```

`XTREAM_PROVIDER_URL`, `XTREAM_USERNAME`, and `XTREAM_PASSWORD` are required.

`XTREAM_WHATS_NEW_PORT` is optional. If omitted, the application is exposed on port `36401`.

`TZ` is optional and defaults to `Europe/Paris`.

`SMTP_USERNAME` and `SMTP_PASSWORD` are only required if you want to use authenticated SMTP email notifications.

When using Dockhand or Portainer environment variables, **no local `.env` file is required**.

Deploy the Stack, then open:

```text
http://YOUR-SERVER-IP:36401
```

If you changed `XTREAM_WHATS_NEW_PORT`, use that host port instead.

For example, with:

```env
XTREAM_WHATS_NEW_PORT=36402
```

open:

```text
http://YOUR-SERVER-IP:36402
```

On first start, the container automatically creates `/data/config.json` and the SQLite database in the persistent Docker volume `xtream-whats-new-data`.

## Docker Compose from the command line

If you prefer the command line, clone or download the repository.

Create your local environment file:

```bash
cp .env.example .env
```

Edit `.env` and enter your provider credentials.

Then start the application:

```bash
docker compose up -d
```

Check the logs:

```bash
docker compose logs --tail=100
```

Docker Compose automatically reads the local `.env` file.

Never commit your `.env` file.

Open:

```text
http://YOUR-SERVER-IP:36401
```

or the host port configured with `XTREAM_WHATS_NEW_PORT`.

## First start

The first scan discovers the categories exposed by your provider.

No country or zone is enabled by default on a fresh installation.

Open **Settings**, enable the country or zone you want to monitor, select the desired VOD and series categories, then save.

Existing catalogue content is first absorbed as a baseline. Later additions are then reported as genuine new content instead of producing thousands of false "new" events.

## Email notifications

SMTP username and password are supplied through environment variables only:

```env
SMTP_USERNAME=your-smtp-user
SMTP_PASSWORD=your-app-password
```

SMTP host, port, TLS/SSL mode, sender, recipients, digest frequency and notification types are configured from the web interface.

When Stack environment variables change, recreate or redeploy the container so the new values are loaded.

## Persistent data

Persistent application data is stored in `/data` inside the container and backed by the named Docker volume:

```text
xtream-whats-new-data
```

It contains:

- `config.json` — non-secret application defaults, created automatically on first start.
- `nouveautes.sqlite3` — active SQLite database.
- `backups/` — application-managed SQLite backups.

Deleting or recreating the container does **not** delete this volume.

Removing the Docker volume **does** delete the application database, settings, history and backups.

The historical filename `nouveautes.sqlite3` is intentionally retained for compatibility.

If you prefer to keep persistent files in a visible host directory such as `/srv/xtream-whats-new`, you may replace the named volume with a bind mount in your own Compose configuration.

## Updating

With Dockhand or Portainer, pull the newest image and redeploy the Stack.

From the command line:

```bash
docker compose pull
docker compose up -d
```

The persistent Docker volume is retained during normal container updates.

## Building locally

If you want to build the application from source instead of using the published GHCR image:

```bash
docker build -t xtream-whats-new:local .
```

The official image is built automatically from this repository by GitHub Actions for:

```text
linux/amd64
linux/arm64
```

## Security

The web interface currently has no built-in authentication.

Do **not** expose it directly to the public Internet. Use a VPN or an authenticated reverse proxy for remote access.

Never commit `.env`, SQLite databases or backup files.

See [SECURITY.md](SECURITY.md).

## Support and contributions

Issues and pull requests are welcome.

This is a best-effort community project. No support response time, maintenance schedule or future feature development is guaranteed.

## Disclaimer

Xtream What's New is an independent project and is not affiliated with Xtream Codes or IPTV providers.

Use it only with services and data sources you are authorized to access.

## License

MIT License. See [LICENSE](LICENSE).
