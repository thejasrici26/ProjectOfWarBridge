# WarBridge

A responsive React + Vite frontend with a Flask backend implementing the WarBridge workflow. SQLite is the default for local demos; PostgreSQL is supported for hosted deployments.

## Run locally

```bash
pnpm install
pnpm dev
```

In a second terminal, set explicit development configuration and start the backend:

```powershell
$env:WARBRIDGE_ENV = "development"
$env:WARBRIDGE_DB = ".\warbridge-demo.db"
$env:SECRET_KEY = "local-development-only-change-this"
python -m pip install -r backend_requirements.txt
python seed_demo.py
python app.py
```

Vite proxies `/api` requests to `http://127.0.0.1:5000`. The known fallback key is available only in explicit development mode. Never use it in a deployment.

`seed_demo.py` creates fictional sample records for the full walkthrough: a displaced user with pending and completed requests, an NGO with public listings, a host with an incoming stay request, a pending NGO and listing for admin review, a private SOS queue entry, and an open report. It prints a randomly generated temporary password on the first run; use it with any listed demo account. The seed command is restricted to explicit development mode, and rerunning it leaves existing records unchanged. Keep this isolated demo database separate from any real-user data.

Create the first administrator account with:

```bash
python create_admin.py
```

The script asks for a username, email, and password and stores only a password hash. Set the same environment variables before running it.

Displaced people, hosts, and NGOs can register through the sign-in form. Host and NGO accounts require administrator verification. New shelters and accommodations also require separate administrator listing approval before they appear publicly.

## API areas

- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`
- `GET /api/public/shelters`, `GET /api/public/accommodations`, `GET /api/public/services`, `GET /api/public/alerts`
- `POST /api/sos`, `GET /api/admin/sos`, `POST /api/requests`
- Verified NGO SOS queue: `GET /api/sos/incoming`, `POST /api/sos/<id>/claim`, `POST /api/sos/<id>/escalate`, `POST /api/sos/<id>/resolve`
- Partner verification: `GET /api/verification/status`, `POST /api/verification/submit`; Admin review/approval/rejection uses `/api/admin/users/<id>/review`, `/verify`, and `/reject`
- Admin notification visibility and retry: `GET /api/admin/notifications/failed`, `POST /api/admin/notifications/<id>/retry`
- NGO/host request handling; `POST /api/shelters`, `/api/accommodations`, `/api/services`, `GET /api/listings/mine`, `PATCH /api/listings/<type>/<id>`, and listing close/reopen actions
- Alert create/edit/archive with expiry and type management; `POST /api/ratings` and `GET /api/ratings/mine` for completed shelter/host requests
- Admin verification, listing moderation, reports, SOS monitoring, audit log, and Admin-only analytics via `GET /api/admin/analytics`
- Health checks: `GET /api/health/live`, `GET /api/health/ready`; internal metrics: `GET /api/internal/metrics`

Mutating API requests require the CSRF token from `GET /api/csrf`.

## Production

Production startup requires a private `SECRET_KEY` of at least 32 characters and `HTTPS_ONLY=1`. Session cookies are secure outside development/test. Run behind HTTPS termination with Gunicorn; do not use `python app.py` in production. If a trusted reverse proxy forwards client IP headers, set `TRUSTED_PROXY_COUNT` to the exact number of trusted proxy hops; forwarded headers are not trusted by default.

```bash
WARBRIDGE_ENV=production SECRET_KEY="<private-random-value>" HTTPS_ONLY=1 gunicorn --workers 2 --bind 127.0.0.1:5000 app:app
```

### Database configuration

SQLite remains the default for local development and demo data. For PostgreSQL, install the backend requirements and configure a PostgreSQL connection URL. The app creates missing tables and applies additive, versioned schema migrations at startup; current data is retained, and migration version 3 adds query indexes.
Migration version 4 adds partner verification review metadata and the provider-neutral emergency-notification queue without removing existing records.

Development can use either SQLite or PostgreSQL:

```powershell
# SQLite (default)
$env:WARBRIDGE_ENV = "development"
$env:WARBRIDGE_DB = ".\warbridge-demo.db"

# Or PostgreSQL
$env:WARBRIDGE_ENV = "development"
$env:WARBRIDGE_DEVELOPMENT_DATABASE_URL = "postgresql://warbridge:password@localhost:5432/warbridge_dev"
$env:WARBRIDGE_DB_POOL_SIZE = "5"
$env:WARBRIDGE_DB_CONNECTION_TIMEOUT = "10"
```

In production, set `WARBRIDGE_DATABASE_URL` (or `DATABASE_URL`) to the PostgreSQL URL. In tests, only `WARBRIDGE_TEST_DATABASE_URL` is used for PostgreSQL, and it is rejected if it matches the production URL. Without a PostgreSQL URL, the app uses SQLite at `WARBRIDGE_DB` or `warbridge.db`.

### Local PostgreSQL integration tests

`docker-compose.yml` starts only a disposable PostgreSQL 16 test service. It binds to loopback port `54329`, uses trust authentication only inside this local test container, and has no persistent volume. Do not reuse this configuration for production. The PostgreSQL test URL is deliberately separate from production settings.

Run the full backend suite with PostgreSQL enabled, then the frontend checks and build:

```powershell
docker compose up -d --wait postgres
python -m pip install -r backend_requirements.txt
$env:WARBRIDGE_ENV = "test"
$env:WARBRIDGE_TEST_DATABASE_URL = "postgresql://warbridge_test@localhost:54329/warbridge_test"
$env:SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python -m unittest discover -s tests -p "test_postgres.py" -v
python run_tests.py
node --test tests/frontend-localization.test.mjs
npx tsc --noEmit
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm test:e2e
pnpm build
docker compose down -v
```

`run_tests.py` fails if any test is skipped, including PostgreSQL tests. Keep the PostgreSQL service running while executing the commands; `docker compose down -v` removes the disposable container and its data when finished. GitHub Actions runs the same PostgreSQL integration tests and checks against its own disposable PostgreSQL service.

The Playwright suite starts its own temporary SQLite backend and generates ephemeral test accounts and administrator credentials for each run. It does not use real credentials or connect to a production database.

To preserve records when moving an existing SQLite demo database to a new, empty PostgreSQL database, set the PostgreSQL target URL and run the importer before switching the application over:

```powershell
$env:WARBRIDGE_ENV = "production"
$env:SECRET_KEY = "<private-random-value-at-least-32-characters>"
$env:HTTPS_ONLY = "1"
$env:WARBRIDGE_DATABASE_URL = "postgresql://warbridge:password@localhost:5432/warbridge"
python migrate_sqlite_to_postgres.py --source .\warbridge-demo.db
```

The importer refuses to copy into tables that already contain records, preserves existing IDs and related records, and commits the copy as one transaction. Back up the source database first. Do not point the importer at a production target containing data.

### SQLite backups

The backup utility creates timestamped SQLite snapshots, runs `PRAGMA integrity_check`, and verifies each archive by restoring it into an isolated temporary database. It supports authenticated AES-256-GCM encrypted output. Backups remain unencrypted unless `--encrypt` is passed.

Configure the backup location, log file, and retention. Retention keeps backups within the configured age plus the newest configured count (defaults: 30 days and 14 files):

```powershell
$env:WARBRIDGE_BACKUP_DIR = "D:\secure-backups"
$env:WARBRIDGE_BACKUP_RETENTION_DAYS = "30"
$env:WARBRIDGE_BACKUP_RETENTION_COUNT = "14"
$env:WARBRIDGE_BACKUP_ENCRYPTION_KEY = "<URL-safe-base64-32-byte-key>"
python db_backup.py backup --encrypt
```

Generate a key once and store it outside the repository in a protected secret store; never put it in source control or beside the encrypted archives:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Backup commands emit structured JSON logs to the console and to `warbridge-backup.log` in the backup directory; override the file location with `WARBRIDGE_BACKUP_LOG`. To test an archive without changing the live database, run:

```powershell
python db_backup.py verify --input D:\secure-backups\warbridge-backup-20261126T001200Z.sqlite3.enc
```

The verifier decrypts when needed, restores into a temporary database, and checks its integrity. Encrypted archives require the same key used to create them; losing or rotating that key makes those archives unrecoverable.

Schedule the one-shot `backup` command with the operating system scheduler so failures and process restarts are managed outside the web app. On Windows, create a daily Task Scheduler task that runs the project's `.venv\Scripts\python.exe` with arguments `db_backup.py backup --encrypt`, set the working directory to the project folder, and run it as the account that owns the backup configuration. On Linux, a cron entry can source a protected environment file:

```cron
15 2 * * * . /etc/warbridge/backup.env && cd /srv/warbridge && /srv/warbridge/.venv/bin/python db_backup.py backup --encrypt
```

Before restoring, stop the application and explicitly confirm replacement. The utility makes and verifies a timestamped safety copy of the current database before atomically installing the restored file:

```powershell
python db_backup.py --database .\warbridge.db restore --input D:\secure-backups\warbridge-backup-20261126T001200Z.sqlite3.enc --confirm-restore
```

The backup utility is SQLite-only and refuses to run when PostgreSQL is configured. For PostgreSQL, use the managed provider's backup/restore tooling or PostgreSQL-native backups. Backups contain sensitive contact and SOS data; encrypt them and store them only in access-controlled, off-site storage. The code prepares local encrypted archives but does not connect to a cloud backup provider.

### Logs and monitoring

The application writes JSON structured logs to stdout. Set `WARBRIDGE_LOG_LEVEL` to `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, or `CRITICAL`. Each request gets a validated `X-Request-ID` (or `X-Correlation-ID`) and returns it in the `X-Request-ID` response header. Request logs include the method, path (not query string), status, and duration. Authentication, account-block, SOS lifecycle, listing moderation, report-decision, and database failure events use safe event fields; request bodies, passwords, CSRF tokens, contact details, addresses, and SOS text are not logged.

`GET /api/health/live` is a database-independent process liveness check. `GET /api/health/ready` checks database connectivity and the current schema migration version. `GET /api/internal/metrics` returns aggregate Prometheus-format metrics and is Admin-only by default. To allow an internal scraper without an Admin session, configure a random `WARBRIDGE_METRICS_TOKEN` of at least 32 characters and send it as `Authorization: Bearer <token>`. Keep the endpoint on a private network or behind HTTPS and store the token in the monitoring service's secret store.

Connect the JSON stdout stream and health/metrics endpoints to an external monitoring service such as your deployment platform's log collector and Prometheus-compatible scraper. Configure alerting for repeated database errors, non-2xx readiness checks, elevated 5xx responses, and unresolved SOS counts. Keep request-body and query-string logging disabled in proxies and monitoring agents as well; do not attach raw request/response payloads.

### Localization

The language selector supports English, Hindi, and Arabic. English is the complete fallback resource. Hindi and Arabic resources are draft structures with missing entries falling back to English; they are not production-ready translations and require native-language and safeguarding review. Arabic sets the document direction to RTL and uses locale-aware number, date, and phone formatting. Review the rendered dashboards, dialogs, mobile layout, and right-to-left spacing after any translation changes.

Run the focused localization checks and frontend type/build checks with:

```powershell
node --test tests/frontend-localization.test.mjs
npx tsc --noEmit
pnpm build
```

### Identity verification adapter

New NGO/Host registrations enter `Submitted`; administrators can mark a case `Under review`, approve it with an optional expiry, or reject it with review notes. Review changes and expiry events are audited. `/api/verification/status` returns the signed-in partner's state, and `/api/verification/submit` is available only when a provider is configured. `WARBRIDGE_VERIFICATION_PROVIDER=mock` is development-only; the default is `disabled`. The mock records a submission only. It does not collect documents or verify identity. Approval remains a manual administrator decision, and expired approvals lose access to partner actions and public listings.

### Emergency notification adapter

The adapter exposes Email, SMS, WhatsApp, and push-notification channels and Queued, Sent, Failed, and Retried states. Notifications are queued only when a development mock is explicitly selected and a channel recipient is configured. Administrators can inspect failed delivery metadata at `GET /api/admin/notifications/failed` and retry eligible records at `POST /api/admin/notifications/<id>/retry`; recipient values and SOS details are never returned by that endpoint or written to structured logs. Retries use bounded exponential backoff. The development mock is not a real dispatch service and must not be used to claim that a person was contacted.

`WARBRIDGE_SOS_ESCALATION_TIMEOUT_SECONDS` defaults to 900 seconds. The timeout is checked when an Admin or verified NGO opens the SOS queue; overdue unclaimed SOS records are marked escalated and become visible to administrators. This is not a continuously running scheduler and does not guarantee a response. Real email/SMS/WhatsApp/push delivery, credentials, recipient routing, monitoring, and a staffed response procedure must be selected and tested before any pilot. WarBridge is not an emergency service; call local emergency services when appropriate.

Production still needs an external monitoring/alerting service, a supported shared database, encrypted off-site backup storage, locally reviewed emergency escalation procedures, native-language review, and a safeguarding/security review. Partner approval is a manual administrative decision only: WarBridge does not collect identity documents or independently verify identity.

### Embedded preview and session cookies

Framing and cross-origin API access are deny-by-default. Configure exact origins for the deployment; do not use wildcards:

```text
FRAME_ANCESTORS="'self',https://your-preview.example"
CORS_ALLOWED_ORIGINS=https://your-preview.example
SESSION_COOKIE_SAMESITE=None
```

`FRAME_ANCESTORS` accepts `'none'` (the default), `'self'`, or comma-separated HTTP(S) origins. `CORS_ALLOWED_ORIGINS` accepts comma-separated HTTP(S) origins. Cross-site iframe cookies require HTTPS, `HTTPS_ONLY=1`, and `SESSION_COOKIE_SAMESITE=None`; the application rejects `SameSite=None` without secure cookies. Set only the exact preview origin(s) you control. The frontend sends credentials, and the backend responds with credentialed CORS headers only for this explicit allowlist.

## Safety and implementation boundaries

An SOS is stored in a private database queue; it is not sent to emergency services, and no response is guaranteed. A verified NGO must explicitly claim it before contact/location details are released. Escalation changes its state and exposes it to administrators; it does not dispatch an external alert.

The app cannot determine identity or intent. NGOs, hosts, and shelters must make access decisions and screen people in person. Women-only eligibility is self-declared, not identity verification. Alerts are in-app only, not SMS or push. Listing freshness depends on partner updates. A real identity/document-check integration, managed production monitoring and encrypted backup storage, human-reviewed translations, and a security and safeguarding review are still required before real deployment.

## Development

The Make environment already manages the preview server.

- `pnpm build` — production frontend build
- `pnpm format` — project formatter
- `python run_tests.py` — backend regression tests; fails on skipped tests
- `node --test tests/frontend-localization.test.mjs` — localization behavior and English-key coverage
- `pnpm test:e2e` — Playwright user workflows, accessibility, responsive, reduced-motion, and RTL checks
- `npx tsc --noEmit` — frontend type check

Copy `.env.example` to a local, untracked environment file or set the variables in your shell. The sample contains placeholders only; do not commit a real secret or recipient address.

## Demo and deployment checklists

### College demo

- Start the Flask API and Vite frontend with the development settings above.
- Seed only the isolated demo database, then sign in using the temporary credentials printed by the seed command.
- Walk through a displaced-user shelter/accommodation request, NGO or host acceptance, SOS claim/escalation/resolution, Admin verification and listing moderation, reports, ratings, analytics, and the audit log.
- Confirm public listings exclude unverified/blocked owners and that SOS contact/location details remain hidden until claim or escalation.
- Run backend tests, localization tests, TypeScript checking, and the frontend build before presenting.

### Pilot or production

- Choose a managed PostgreSQL provider, apply migrations, and test restore and rollback using a separate database before cutover.
- Configure HTTPS, cookies, exact CORS/frame origin allowlists, secret storage, encrypted off-site backups, retention, health monitoring, metrics scraping, and alert routing.
- Complete administrator/NGO onboarding, safeguarding review, privacy notice/consent/retention procedures, real verification-provider selection, and a staffed SOS response runbook.
- Keep identity and emergency providers disabled until credentials, recipients, human ownership, and failure/retry behavior have been verified in a non-production environment.
- Obtain native-language review for Hindi and Arabic; validate RTL layout on mobile and desktop.

### Migration rollback

Back up and verify the source database before deploying a schema migration. Migrations are additive and the application currently has no automatic schema downgrade. If startup or validation fails, restore the verified pre-deployment database snapshot to a separate database, redeploy the previous application version, and validate health, authentication, and listings before reconnecting traffic. Never test rollback by overwriting the live database.

The background image is included at `public/warbridge-camp.png`; the app does not depend on an expiring generated-image URL.
