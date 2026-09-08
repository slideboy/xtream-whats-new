# Publishing notes

Maintainer checklist for Xtream What's New.

## Release policy

Docker images are published **only for stable release tags matching `vMAJOR.MINOR.PATCH`**.

Normal commits to `main`, including documentation changes, do not publish a new Docker image.

Examples:

```text
README update        → no Docker image
Documentation update → no Docker image
Tag vMAJOR.MINOR.PATCH → Docker image published
```

The publishing workflow is:

```text
.github/workflows/docker-publish.yml
```

## Version numbering

Xtream What's New follows semantic versioning:

```text
vMAJOR.MINOR.PATCH
```

Examples:

```text
v1.0.1 → bug fix
v1.1.0 → new backward-compatible feature
v2.0.0 → major or incompatible change
```

Do not create a new release only for README or documentation changes.

## Docker images

When a stable release tag matching:

```text
vMAJOR.MINOR.PATCH
```

is published, GitHub Actions builds the Docker image for:

```text
linux/amd64
linux/arm64
```

and publishes the following GHCR tags:

```text
ghcr.io/slideboy/xtream-whats-new:vMAJOR.MINOR.PATCH
ghcr.io/slideboy/xtream-whats-new:MAJOR.MINOR.PATCH
ghcr.io/slideboy/xtream-whats-new:MAJOR.MINOR
ghcr.io/slideboy/xtream-whats-new:latest
```

`latest` therefore points to the most recent official release.

The public Compose file continues to use:

```text
ghcr.io/slideboy/xtream-whats-new:latest
```

Users who prefer to pin a specific version may instead use the corresponding stable tag, for example:

```text
ghcr.io/slideboy/xtream-whats-new:vMAJOR.MINOR.PATCH
```

## Publishing a new release

Before publishing:

- Make sure the intended application changes are committed to `main`.
- Never commit `.env`.
- Never commit SQLite databases.
- Never commit `data/backups/`.
- Confirm that the **Basic checks** GitHub Action is green.
- Test important changes before creating the release.
- Update the README if installation or configuration has changed.

Then:

1. Open **Releases** on GitHub.
2. Choose **Draft a new release**.
3. Create a stable tag using semantic versioning:

```text
vMAJOR.MINOR.PATCH
```

4. Target the `main` branch.
5. Add a clear release title and release notes.
6. Publish the Release.

Pushing a stable `vMAJOR.MINOR.PATCH` tag automatically triggers the **Publish Docker image** workflow.

## After publishing

Verify that:

- The **Publish Docker image** workflow is green.
- The new version appears under **Packages → xtream-whats-new**.
- The versioned Docker tag exists.
- `latest` points to the new release.
- The public GHCR package can still be pulled without authentication.

Example:

```bash
docker pull ghcr.io/slideboy/xtream-whats-new:vMAJOR.MINOR.PATCH
```

Optionally test:

```bash
docker pull ghcr.io/slideboy/xtream-whats-new:latest
```

## GHCR package visibility

The `xtream-whats-new` package is intended to remain **Public** so Docker, Dockhand, Portainer and Docker Compose users can pull the image without GitHub authentication.

Do not change the package visibility unless there is a specific reason to do so.

## Fresh-install testing

For significant releases, test a fresh deployment using the published image rather than an existing development installation.

Recommended checks:

- Container starts successfully.
- Healthcheck becomes healthy.
- Web interface is reachable.
- Provider API connection works.
- Fresh installation starts with no country forced enabled.
- Baseline creation does not generate false historical events.
- Manual and automatic scans work.
- SQLite backup works.
- Persistent data survives container recreation.
- FR/EN interface works.
- Email notifications work when SMTP is configured.

## Support

Xtream What's New is a best-effort community project.

Publishing a release does not imply any guaranteed support response time, maintenance schedule or commitment to future development.
