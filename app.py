import hashlib
import logging
import os
import re
import secrets
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import Flask, Response, g, has_request_context, jsonify, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from database import DatabaseIntegrityError, connect_database
from emergency_adapter import (
    NOTIFICATION_CHANNELS,
    NOTIFICATION_STATES,
    DisabledEmergencyNotificationProvider,
    NotificationDispatchError,
    NotificationResult,
    ProviderDisabledError as NotificationProviderDisabledError,
    create_emergency_notification_provider,
)
from structured_logging import JsonLogFormatter, LOG_LEVELS, REQUEST_ID_CONTEXT
from verification_adapter import (
    VERIFICATION_STATES,
    ProviderDisabledError as VerificationProviderDisabledError,
    create_verification_provider,
)


APP_ENV = os.getenv("WARBRIDGE_ENV", "production").strip().lower()
CURRENT_SCHEMA_VERSION = 4
PROCESS_STARTED_AT = time.monotonic()
REQUEST_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
API_ERROR_MESSAGES = {
    400: "Bad request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    429: "Too many requests",
    413: "Request too large",
    500: "Internal server error",
}
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]*$")

app = Flask(__name__)
verification_provider = create_verification_provider(
    os.getenv("WARBRIDGE_VERIFICATION_PROVIDER", "disabled").strip().lower(),
    APP_ENV,
)
emergency_notification_provider = create_emergency_notification_provider(
    os.getenv("WARBRIDGE_EMERGENCY_PROVIDER", "disabled").strip().lower(),
    APP_ENV,
)
logger = logging.getLogger("warbridge")
level_name = os.getenv("WARBRIDGE_LOG_LEVEL", "INFO").strip().upper()
if level_name not in LOG_LEVELS:
    raise RuntimeError("WARBRIDGE_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
if not any(getattr(handler, "_warbridge_json", False) for handler in logger.handlers):
    log_handler = logging.StreamHandler(sys.stdout)
    log_handler.setFormatter(JsonLogFormatter())
    log_handler._warbridge_json = True
    logger.addHandler(log_handler)
logger.setLevel(LOG_LEVELS[level_name])
logger.propagate = False
app.logger.disabled = True
logging.getLogger("werkzeug").disabled = True

METRICS_TOKEN = os.getenv("WARBRIDGE_METRICS_TOKEN", "").strip() or None
if METRICS_TOKEN and len(METRICS_TOKEN) < 32:
    raise RuntimeError("WARBRIDGE_METRICS_TOKEN must be at least 32 characters")
try:
    SOS_ESCALATION_TIMEOUT_SECONDS = int(os.getenv("WARBRIDGE_SOS_ESCALATION_TIMEOUT_SECONDS", "900"))
except ValueError as error:
    raise RuntimeError("WARBRIDGE_SOS_ESCALATION_TIMEOUT_SECONDS must be a positive integer") from error
if SOS_ESCALATION_TIMEOUT_SECONDS < 1:
    raise RuntimeError("WARBRIDGE_SOS_ESCALATION_TIMEOUT_SECONDS must be a positive integer")

secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    if APP_ENV == "development":
        secret_key = "development-only-change-me"
    else:
        raise RuntimeError("SECRET_KEY must be configured outside explicit development mode")
if APP_ENV not in ("development", "test") and os.getenv("HTTPS_ONLY") != "1":
    raise RuntimeError("HTTPS_ONLY=1 is required outside development and test modes")
if APP_ENV not in ("development", "test") and len(secret_key) < 32:
    raise RuntimeError("SECRET_KEY must be at least 32 characters outside development and test modes")

def normalize_origin(candidate, env_name):
    try:
        parsed = urlsplit(candidate)
        parsed.port
    except ValueError as error:
        raise RuntimeError(f"{env_name} must contain valid HTTP(S) origins") from error
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "*" in candidate
        or any(character.isspace() or character in ";'\"\\<>" for character in candidate)
        or APP_ENV not in ("development", "test") and parsed.scheme != "https"
    ):
        raise RuntimeError(f"{env_name} must contain valid HTTP(S) origins")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parsed.port
    if port == (443 if parsed.scheme == "https" else 80):
        port = None
    port_suffix = f":{port}" if port else ""
    return f"{parsed.scheme}://{hostname}{port_suffix}"


def parse_origin_list(env_name):
    origins = []
    for candidate in filter(None, (item.strip() for item in os.getenv(env_name, "").split(","))):
        origins.append(normalize_origin(candidate, env_name))
    return tuple(dict.fromkeys(origins))


frame_ancestors = os.getenv("FRAME_ANCESTORS", "'none'").strip()
if frame_ancestors == "'none'":
    FRAME_ANCESTORS = ("'none'",)
else:
    frame_values = []
    for candidate in filter(None, (item.strip() for item in frame_ancestors.split(","))):
        if candidate == "'self'":
            frame_values.append(candidate)
            continue
        frame_values.append(normalize_origin(candidate, "FRAME_ANCESTORS"))
    if not frame_values:
        raise RuntimeError("FRAME_ANCESTORS must not be empty")
    FRAME_ANCESTORS = tuple(dict.fromkeys(frame_values))

ALLOWED_CORS_ORIGINS = parse_origin_list("CORS_ALLOWED_ORIGINS")
same_site = os.getenv("SESSION_COOKIE_SAMESITE", "Lax").strip().capitalize()
if same_site not in ("Lax", "Strict", "None"):
    raise RuntimeError("SESSION_COOKIE_SAMESITE must be Lax, Strict, or None")
cookie_secure = APP_ENV not in ("development", "test") or os.getenv("HTTPS_ONLY") == "1"
if same_site == "None" and not cookie_secure:
    raise RuntimeError("SESSION_COOKIE_SAMESITE=None requires HTTPS_ONLY=1")

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=same_site,
    SESSION_COOKIE_SECURE=cookie_secure,
)
try:
    MAX_CONTENT_LENGTH = int(os.getenv("WARBRIDGE_MAX_CONTENT_LENGTH", str(1024 * 1024)))
except ValueError as error:
    raise RuntimeError("WARBRIDGE_MAX_CONTENT_LENGTH must be a positive integer") from error
if not 1 <= MAX_CONTENT_LENGTH <= 10 * 1024 * 1024:
    raise RuntimeError("WARBRIDGE_MAX_CONTENT_LENGTH must be between 1 byte and 10 MiB")
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
try:
    trusted_proxy_count = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
except ValueError as error:
    raise RuntimeError("TRUSTED_PROXY_COUNT must be a non-negative integer") from error
if trusted_proxy_count < 0:
    raise RuntimeError("TRUSTED_PROXY_COUNT must be a non-negative integer")
if trusted_proxy_count:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_count)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def is_valid_email(value):
    return (
        isinstance(value, str)
        and len(value) <= 254
        and EMAIL_PATTERN.fullmatch(value) is not None
    )


def is_valid_phone(value):
    if value in (None, ""):
        return True
    if not isinstance(value, str) or len(value) > 40 or not PHONE_PATTERN.fullmatch(value):
        return False
    digits = sum(character.isdigit() for character in value)
    return 7 <= digits <= 15


def log_event(level, event, message, **fields):
    if has_request_context():
        fields.setdefault("request_id", getattr(g, "request_id", None))
    logger.log(
        level,
        message,
        extra={"event": event, **{key: value for key, value in fields.items() if value is not None}},
    )


def get_db():
    if "db" not in g:
        g.db = connect_database()
    return g.db


def ensure_column(db, table, column, definition):
    columns = db.table_columns(table)
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if FRAME_ANCESTORS == ("'none'",):
        response.headers.setdefault("X-Frame-Options", "DENY")
    elif FRAME_ANCESTORS == ("'self'",):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Content-Security-Policy",
        f"default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors {' '.join(FRAME_ANCESTORS)}; form-action 'self'",
    )
    origin = request.headers.get("Origin")
    if origin and origin in ALLOWED_CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, X-CSRF-Token, X-Request-ID, X-Correlation-ID, Authorization"
        )
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
        response.vary.add("Origin")
    if APP_ENV not in ("development", "test"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
        duration_ms = round((time.perf_counter() - g.request_started_at) * 1000, 2)
        log_event(
            logging.INFO,
            "http_request_completed",
            "HTTP request completed",
            method=request.method,
            path=request.url_rule.rule if request.url_rule else "unmatched",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    return response


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('DISPLACED','HOST','NGO','ADMIN')),
            gender TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shelters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngo_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            area TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            beds_available INTEGER NOT NULL DEFAULT 0,
            women_safe INTEGER NOT NULL DEFAULT 0,
            family_friendly INTEGER NOT NULL DEFAULT 0,
            verified INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            closed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accommodations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL REFERENCES users(id),
            city TEXT NOT NULL,
            area TEXT NOT NULL,
            address TEXT,
            rooms INTEGER NOT NULL,
            rooms_available INTEGER NOT NULL DEFAULT 0,
            women_only INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            closed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS help_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_id INTEGER REFERENCES users(id),
            handler_id INTEGER REFERENCES users(id),
            shelter_id INTEGER REFERENCES shelters(id),
            accommodation_id INTEGER REFERENCES accommodations(id),
            type TEXT NOT NULL,
            message TEXT,
            requester_name TEXT,
            contact TEXT,
            location_text TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            is_sos INTEGER NOT NULL DEFAULT 0,
            handled_by INTEGER REFERENCES users(id),
            claimed_by INTEGER REFERENCES users(id),
            claimed_at TEXT,
            escalated_at TEXT,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS emergency_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL REFERENCES help_requests(id),
            channel TEXT NOT NULL CHECK(channel IN ('Email','SMS','WhatsApp','Push notification')),
            status TEXT NOT NULL DEFAULT 'Queued' CHECK(status IN ('Queued','Sent','Failed','Retried')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error_code TEXT,
            next_attempt_at TEXT,
            last_attempt_at TEXT,
            sent_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(request_id,channel)
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL REFERENCES users(id),
            listing_type TEXT NOT NULL,
            listing_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            admin_id INTEGER REFERENCES users(id),
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(reporter_id, listing_type, listing_id)
        );
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            listing_type TEXT NOT NULL,
            listing_id INTEGER NOT NULL,
            stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
            comment TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, listing_type, listing_id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngo_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL,
            expires_at TEXT,
            blocked INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ngo_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            city TEXT NOT NULL,
            opening_hours TEXT,
            contact TEXT,
            address TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            closed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            detail TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_limit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            attempted_at DOUBLE PRECISION NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rate_limit_events_scope_key_time
            ON rate_limit_events(scope, key_hash, attempted_at);
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    current_version = db.execute("SELECT COALESCE(MAX(version),0) AS version FROM schema_migrations").fetchone()["version"]
    if current_version < CURRENT_SCHEMA_VERSION:
        db.execute("BEGIN IMMEDIATE")
        current_version = db.execute(
            "SELECT COALESCE(MAX(version),0) AS version FROM schema_migrations"
        ).fetchone()["version"]
    if current_version < 1:
        accommodation_columns = db.table_columns("accommodations")
        if "rooms_available" not in accommodation_columns:
            ensure_column(db, "accommodations", "rooms_available", "INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE accommodations SET rooms_available=rooms")
        ensure_column(db, "help_requests", "requester_name", "TEXT")
        ensure_column(db, "help_requests", "claimed_by", "INTEGER REFERENCES users(id)")
        ensure_column(db, "help_requests", "claimed_at", "TEXT")
        ensure_column(db, "help_requests", "escalated_at", "TEXT")
        db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)", (utcnow(),))
        current_version = 1
    if current_version < 2:
        ensure_column(db, "shelters", "closed", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "services", "closed", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "alerts", "archived", "INTEGER NOT NULL DEFAULT 0")
        db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(2,?)", (utcnow(),))
        current_version = 2
    if current_version < 3:
        db.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_help_requests_status ON help_requests(status);
            CREATE INDEX IF NOT EXISTS idx_help_requests_sos_status ON help_requests(is_sos,status);
            CREATE INDEX IF NOT EXISTS idx_shelters_verification_block ON shelters(verified,blocked);
            CREATE INDEX IF NOT EXISTS idx_accommodations_verification_block ON accommodations(verified,blocked);
            CREATE INDEX IF NOT EXISTS idx_services_verification_block ON services(verified,blocked);
            CREATE INDEX IF NOT EXISTS idx_alerts_expires_at ON alerts(expires_at);
            CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
            """
        )
        db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(3,?)", (utcnow(),))
        current_version = 3
    if current_version < 4:
        ensure_column(db, "users", "verification_status", "TEXT NOT NULL DEFAULT 'Not started'")
        ensure_column(db, "users", "verification_review_notes", "TEXT")
        ensure_column(db, "users", "verification_submitted_at", "TEXT")
        ensure_column(db, "users", "verification_reviewed_at", "TEXT")
        ensure_column(db, "users", "verification_expires_at", "TEXT")
        db.execute(
            """UPDATE users SET verification_status='Submitted',
               verification_submitted_at=created_at
               WHERE role IN ('HOST','NGO') AND verified=0
                 AND verification_status='Not started'"""
        )
        db.execute(
            """UPDATE users SET verification_status='Approved',
               verification_reviewed_at=created_at
               WHERE role IN ('HOST','NGO') AND verified=1
                 AND verification_status='Not started'"""
        )
        db.executescript(
            """CREATE INDEX IF NOT EXISTS idx_notifications_request_status
               ON emergency_notifications(request_id,status);
            """
        )
        db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(4,?)", (utcnow(),))
    db.commit()

    admin_email = os.getenv("WARBRIDGE_ADMIN_EMAIL")
    admin_password = os.getenv("WARBRIDGE_ADMIN_PASSWORD")
    if admin_email and admin_password:
        if not is_valid_email(admin_email.lower()) or not 12 <= len(admin_password) <= 128:
            raise RuntimeError("WARBRIDGE_ADMIN_EMAIL must be valid and WARBRIDGE_ADMIN_PASSWORD must be 12-128 characters")
        existing = db.execute("SELECT id FROM users WHERE email = ?", (admin_email.lower(),)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO users(name,email,password_hash,role,verified,created_at) VALUES(?,?,?,?,1,?)",
                ("Administrator", admin_email.lower(), generate_password_hash(admin_password), "ADMIN", utcnow()),
            )
            db.commit()


@app.before_request
def setup():
    request_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    if not request_id or not REQUEST_ID_PATTERN.fullmatch(request_id):
        request_id = str(uuid.uuid4())
    g.request_id = request_id
    g.request_started_at = time.perf_counter()
    g.request_id_context_token = REQUEST_ID_CONTEXT.set(request_id)
    if request.endpoint not in ("health_live", "health_ready"):
        init_db()
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


@app.teardown_request
def clear_request_context(_error):
    token = g.pop("request_id_context_token", None)
    if token is not None:
        REQUEST_ID_CONTEXT.reset(token)


def api_error_response(status_code, message):
    request_id = getattr(g, "request_id", None)
    payload = {"error": message}
    if request_id:
        payload["request_id"] = request_id
    return jsonify(payload), status_code


def handle_http_error(error):
    status_code = error.code or 500
    original = getattr(error, "original_exception", None)
    log_event(
        logging.ERROR if status_code >= 500 else logging.WARNING,
        "http_error",
        "HTTP error response",
        status_code=status_code,
        error_type=type(original or error).__name__,
    )
    return api_error_response(
        status_code,
        API_ERROR_MESSAGES.get(status_code, "Request failed"),
    )


for error_status in (400, 401, 403, 404, 409, 413, 429, 500):
    app.register_error_handler(error_status, handle_http_error)


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        return handle_http_error(error)
    log_event(
        logging.ERROR,
        "unhandled_exception",
        "Unhandled request exception",
        error_type=type(error).__name__,
    )
    return api_error_response(500, API_ERROR_MESSAGES[500])


def require_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        supplied = request.headers.get("X-CSRF-Token") or (request.get_json(silent=True) or {}).get("_csrf")
        if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
            return jsonify({"error": "Invalid CSRF token"}), 403
    return None


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def role_required(*roles):
    def decorator(fn):
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "Authentication required"}), 401
            if user["blocked"]:
                log_event(
                    logging.WARNING,
                    "account_blocked",
                    "Blocked account access denied",
                    user_id=user["id"],
                    role=user["role"],
                    outcome="denied",
                )
                return jsonify({"error": "Account blocked"}), 403
            if user["role"] not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return fn(user, *args, **kwargs)
        wrapped.__name__ = fn.__name__
        return wrapped
    return decorator


def verified_required(user):
    if user["role"] == "ADMIN":
        return True
    if not user["verified"]:
        return False
    expires_at = user["verification_expires_at"]
    return not expires_at or expires_at > utcnow()


def audit(actor_id, action, target_type=None, target_id=None, detail=None):
    get_db().execute(
        "INSERT INTO audit_log(actor_id,action,target_type,target_id,detail,created_at) VALUES(?,?,?,?,?,?)",
        (actor_id, action, target_type, target_id, detail, utcnow()),
    )


def audit_and_commit(db, actor_id, action, target_type=None, target_id=None, detail=None):
    audit(actor_id, action, target_type, target_id, detail)
    db.commit()


def rate_limit_key(value):
    return hashlib.sha256(f"{app.config['SECRET_KEY']}:{value}".encode()).hexdigest()


def allow_rate_limited_attempt(scope, value, limit, window_seconds):
    db = get_db()
    key_hash = rate_limit_key(value)
    now = time.time()
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        "DELETE FROM rate_limit_events WHERE scope=? AND key_hash=? AND attempted_at < ?",
        (scope, key_hash, now - window_seconds),
    )
    count = db.execute(
        "SELECT COUNT(*) AS count FROM rate_limit_events WHERE scope=? AND key_hash=?",
        (scope, key_hash),
    ).fetchone()["count"]
    if count >= limit:
        db.commit()
        return False
    db.execute(
        "INSERT INTO rate_limit_events(scope,key_hash,attempted_at) VALUES(?,?,?)",
        (scope, key_hash, now),
    )
    db.commit()
    return True


def queue_configured_sos_notifications(request_id):
    if isinstance(emergency_notification_provider, DisabledEmergencyNotificationProvider):
        return
    db = get_db()
    now = utcnow()
    for channel in NOTIFICATION_CHANNELS:
        env_channel = channel.upper().replace(" ", "_")
        recipient = os.getenv(f"WARBRIDGE_EMERGENCY_{env_channel}_RECIPIENT", "").strip()
        if not recipient:
            continue
        db.execute(
            """INSERT INTO emergency_notifications(request_id,channel,status,created_at,updated_at)
               VALUES(?,?,'Queued',?,?) ON CONFLICT(request_id,channel) DO NOTHING""",
            (request_id, channel, now, now),
        )
        notification = db.execute(
            """SELECT id,request_id,channel,status,attempt_count
               FROM emergency_notifications WHERE request_id=? AND channel=?""",
            (request_id, channel),
        ).fetchone()
        db.commit()
        if notification and notification["status"] == "Queued":
            attempt_emergency_notification(notification, recipient)


def attempt_emergency_notification(row, recipient, retry=False):
    if isinstance(emergency_notification_provider, DisabledEmergencyNotificationProvider):
        raise NotificationProviderDisabledError("Emergency notification provider is disabled")
    db = get_db()
    now = utcnow()
    attempts = row["attempt_count"] + 1
    in_progress_status = "Retried" if retry else "Queued"
    db.execute(
        """UPDATE emergency_notifications SET status=?,attempt_count=?,last_attempt_at=?,
           updated_at=? WHERE id=?""",
        (in_progress_status, attempts, now, now, row["id"]),
    )
    db.commit()
    try:
        result = emergency_notification_provider.send(row["channel"], recipient, row["request_id"])
    except NotificationProviderDisabledError:
        raise
    except NotificationDispatchError as error:
        result = NotificationResult(sent=False, error_code=error.error_code)
    if result.sent:
        status = "Sent"
        error_code = None
        sent_at = now
        next_attempt_at = None
    else:
        status = "Retried" if retry else "Failed"
        candidate = result.error_code or "delivery_failed"
        error_code = candidate if re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", candidate) else "delivery_failed"
        sent_at = None
        next_attempt_at = (
            datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * (2 ** min(attempts - 1, 7))))
        ).isoformat()
    db.execute(
        """UPDATE emergency_notifications SET status=?,last_error_code=?,sent_at=?,
           next_attempt_at=?,updated_at=? WHERE id=?""",
        (status, error_code, sent_at, next_attempt_at, utcnow(), row["id"]),
    )
    db.commit()
    if status not in NOTIFICATION_STATES:
        raise RuntimeError("Notification provider returned an unsupported status")
    log_event(
        logging.INFO if result.sent else logging.WARNING,
        "emergency_notification_attempt",
        "Emergency notification attempt completed",
        target_type="emergency_notification",
        target_id=row["id"],
        channel=row["channel"],
        outcome=status.lower(),
        error_code=error_code,
    )
    return status


def escalate_overdue_sos():
    db = get_db()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=SOS_ESCALATION_TIMEOUT_SECONDS)
    ).isoformat()
    db.execute("BEGIN IMMEDIATE")
    rows = db.execute(
        """SELECT id FROM help_requests
           WHERE is_sos=1 AND status='Pending' AND claimed_by IS NULL AND created_at<=?""",
        (cutoff,),
    ).fetchall()
    now = utcnow()
    for row in rows:
        updated = db.execute(
            """UPDATE help_requests SET status='Escalated',escalated_at=?,updated_at=?
               WHERE id=? AND is_sos=1 AND status='Pending' AND claimed_by IS NULL""",
            (now, now, row["id"]),
        )
        if updated.rowcount:
            audit(None, "sos_escalated_timeout", "help_request", row["id"])
            log_event(
                logging.WARNING,
                "sos_escalated_timeout",
                "Unclaimed SOS escalated after its response timeout",
                target_type="help_request",
                target_id=row["id"],
                outcome="escalated",
            )
    if rows:
        db.commit()


def clear_rate_limited_attempts(scope, value):
    db = get_db()
    db.execute(
        "DELETE FROM rate_limit_events WHERE scope=? AND key_hash=?",
        (scope, rate_limit_key(value)),
    )
    db.commit()


def parse_expiry(value):
    if value in (None, ""):
        return None
    try:
        expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        return False
    return expires.astimezone(timezone.utc).isoformat()


def protected_request(row):
    item = json_row(row)
    if item["status"] != "Accepted":
        item.pop("contact", None)
        item.pop("location_text", None)
    return item


def protected_sos(row, include_private=False):
    item = json_row(row)
    if not include_private:
        item.pop("requester_name", None)
        item.pop("contact", None)
        item.pop("location_text", None)
    item["has_contact"] = bool(row["contact"])
    item["has_location"] = bool(row["location_text"])
    return item


def json_row(row):
    return dict(row) if row else None


def public_user(user):
    if not user:
        return None
    verification_status = user["verification_status"]
    expires_at = user["verification_expires_at"]
    is_verified = bool(user["verified"] and (not expires_at or expires_at > utcnow()))
    if user["verified"] and not is_verified:
        verification_status = "Expired"
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "gender": user["gender"],
        "verified": is_verified,
        "verification_status": verification_status,
        "verification_expires_at": expires_at,
    }


@app.get("/api/csrf")
def csrf():
    return jsonify({"csrfToken": session["csrf_token"]})


@app.get("/api/health/live")
def health_live():
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(time.monotonic() - PROCESS_STARTED_AT),
    })


@app.get("/api/health/ready")
def health_ready():
    try:
        init_db()
        db = get_db()
        db.execute("SELECT 1").fetchone()
        schema_version = db.execute(
            "SELECT COALESCE(MAX(version),0) AS version FROM schema_migrations"
        ).fetchone()["version"]
        if schema_version != CURRENT_SCHEMA_VERSION:
            log_event(
                logging.WARNING,
                "readiness_check_failed",
                "Database schema version is not current",
                schema_version=schema_version,
            )
            return jsonify({
                "status": "not_ready",
                "checks": {"database": "ok", "migrations": "out_of_date"},
            }), 503
        return jsonify({
            "status": "ready",
            "checks": {"database": "ok", "migrations": "current"},
            "schema_version": schema_version,
        })
    except Exception as error:
        log_event(
            logging.ERROR,
            "readiness_check_failed",
            "Database readiness check failed",
            error_type=type(error).__name__,
        )
        return jsonify({
            "status": "not_ready",
            "checks": {"database": "unavailable", "migrations": "unknown"},
        }), 503


@app.get("/api/internal/metrics")
def internal_metrics():
    token = request.headers.get("Authorization", "")
    token_authorized = bool(
        METRICS_TOKEN
        and secrets.compare_digest(token, f"Bearer {METRICS_TOKEN}")
    )
    if not token_authorized:
        user = current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        if user["blocked"]:
            log_event(
                logging.WARNING,
                "account_blocked",
                "Blocked account attempted metrics access",
                outcome="denied",
                role=user["role"],
            )
            return jsonify({"error": "Account blocked"}), 403
        if user["role"] != "ADMIN":
            return jsonify({"error": "Forbidden"}), 403

    db = get_db()
    user_rows = db.execute(
        "SELECT role,COUNT(*) AS count FROM users GROUP BY role"
    ).fetchall()
    user_counts = {row["role"]: row["count"] for row in user_rows}
    request_rows = db.execute(
        """SELECT status,COUNT(*) AS count FROM help_requests
           WHERE is_sos=0 AND status IN ('Pending','Accepted')
           GROUP BY status"""
    ).fetchall()
    request_counts = {row["status"]: row["count"] for row in request_rows}
    unresolved_sos = db.execute(
        """SELECT COUNT(*) AS count FROM help_requests
           WHERE is_sos=1 AND status IN ('Pending','Accepted','Escalated')"""
    ).fetchone()["count"]
    open_reports = db.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE status='Open'"
    ).fetchone()["count"]
    schema_version = db.execute(
        "SELECT COALESCE(MAX(version),0) AS version FROM schema_migrations"
    ).fetchone()["version"]

    lines = [
        "# HELP warbridge_users_total Registered users by role",
        "# TYPE warbridge_users_total gauge",
    ]
    for role in ("DISPLACED", "HOST", "NGO", "ADMIN"):
        lines.append(f'warbridge_users_total{{role="{role}"}} {user_counts.get(role, 0)}')
    lines.extend((
        "# HELP warbridge_active_requests Active non-SOS requests by status",
        "# TYPE warbridge_active_requests gauge",
    ))
    for status in ("Pending", "Accepted"):
        lines.append(
            f'warbridge_active_requests{{status="{status.lower()}"}} '
            f"{request_counts.get(status, 0)}"
        )
    lines.extend((
        "# HELP warbridge_unresolved_sos_total Unresolved SOS requests",
        "# TYPE warbridge_unresolved_sos_total gauge",
        f"warbridge_unresolved_sos_total {unresolved_sos}",
        "# HELP warbridge_open_reports_total Open reports",
        "# TYPE warbridge_open_reports_total gauge",
        f"warbridge_open_reports_total {open_reports}",
        "# HELP warbridge_database_schema_version Applied schema version",
        "# TYPE warbridge_database_schema_version gauge",
        f"warbridge_database_schema_version {schema_version}",
    ))
    log_event(
        logging.INFO,
        "metrics_scraped",
        "Internal metrics endpoint accessed",
        outcome="authorized",
        reason="token" if token_authorized else "admin",
    )
    response = Response(
        "\n".join(lines) + "\n",
        mimetype="text/plain; version=0.0.4",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/auth/register")
def register():
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    role = str(data.get("role", "")).upper()
    gender = str(data.get("gender", "")).strip() or None
    if not name or not is_valid_email(email) or not 12 <= len(password) <= 128:
        return jsonify({"error": "Enter a valid email and a password between 12 and 128 characters"}), 400
    if role not in ("DISPLACED", "HOST", "NGO"):
        return jsonify({"error": "Role must be Displaced, Host or NGO"}), 400
    db = get_db()
    if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        return jsonify({"error": "An account already exists for this email"}), 409
    if role in ("HOST", "NGO") and db.execute(
        "SELECT id FROM users WHERE role=? AND LOWER(name)=LOWER(?)",
        (role, name),
    ).fetchone():
        return jsonify({"error": "An account already exists for this partner name"}), 409
    cur = db.execute(
        "INSERT INTO users(name,email,password_hash,role,gender,verified,blocked,created_at) VALUES(?,?,?,?,?,?,0,?)",
        (name, email, generate_password_hash(password), role, gender, 0, utcnow()),
    )
    if role in ("HOST", "NGO"):
        db.execute(
            """UPDATE users SET verification_status='Submitted',
               verification_submitted_at=? WHERE id=?""",
            (utcnow(), cur.lastrowid),
        )
    db.commit()
    session.clear()
    session["user_id"] = cur.lastrowid
    session["csrf_token"] = secrets.token_urlsafe(32)
    user = db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"user": public_user(user), "csrfToken": session["csrf_token"]})


@app.post("/api/auth/login")
def login():
    denied = require_csrf()
    if denied:
        return denied
    ip = request.remote_addr or "unknown"
    if not allow_rate_limited_attempt("login", ip, 5, 300):
        log_event(
            logging.WARNING,
            "login_rate_limited",
            "Login attempt was rate limited",
            reason="rate_limit_exceeded",
        )
        return jsonify({"error": "Too many login attempts. Try again later."}), 429
    data = request.get_json(silent=True) or {}
    identity = str(data.get("identity", "")).strip().lower()
    role = str(data.get("role", "")).strip().upper()
    password = str(data.get("password", ""))
    if role not in ("DISPLACED", "HOST", "NGO", "ADMIN"):
        return jsonify({"error": "Choose a valid WarBridge account role"}), 400
    if not identity or not password:
        return jsonify({"error": "Name and password are required"}), 400
    users = get_db().execute(
        """SELECT * FROM users
           WHERE role=? AND (LOWER(name)=? OR LOWER(email)=?)""",
        (role, identity, identity),
    ).fetchall()
    matches = [user for user in users if check_password_hash(user["password_hash"], password)]
    if len(matches) > 1:
        log_event(
            logging.WARNING,
            "login_failed",
            "Login attempt matched multiple accounts",
            reason="ambiguous_identity",
        )
        return jsonify({"error": "This name matches multiple accounts. Sign in with the account email instead."}), 409
    if not matches:
        log_event(
            logging.WARNING,
            "login_failed",
            "Login attempt failed",
            reason="invalid_credentials",
        )
        return jsonify({"error": "Invalid name or password"}), 401
    user = matches[0]
    clear_rate_limited_attempts("login", ip)
    if user["blocked"]:
        log_event(
            logging.WARNING,
            "account_blocked",
            "Blocked account login denied",
            user_id=user["id"],
            role=user["role"],
            outcome="denied",
        )
        return jsonify({"error": "Account blocked"}), 403
    session.clear()
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    log_event(
        logging.INFO,
        "login_succeeded",
        "User authenticated",
        user_id=user["id"],
        role=user["role"],
        outcome="allowed",
    )
    return jsonify({"user": public_user(user), "csrfToken": session["csrf_token"]})


@app.post("/api/auth/logout")
def logout():
    denied = require_csrf()
    if denied:
        return denied
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/me")
def me():
    user = current_user()
    return jsonify({"user": public_user(user)})


@app.get("/api/verification/status")
@role_required("HOST", "NGO")
def verification_status(user):
    status = public_user(user)
    return jsonify({
        "status": status["verification_status"],
        "expires_at": status["verification_expires_at"],
        "review_notes": user["verification_review_notes"],
        "submitted_at": user["verification_submitted_at"],
        "reviewed_at": user["verification_reviewed_at"],
    })


@app.post("/api/verification/submit")
@role_required("HOST", "NGO")
def submit_verification(user):
    denied = require_csrf()
    if denied:
        return denied
    if user["verified"] and verified_required(user):
        return jsonify({"error": "This account is already verified"}), 409
    try:
        submission = verification_provider.submit(str(user["id"]))
    except VerificationProviderDisabledError:
        return jsonify({"error": "Identity verification provider is disabled; contact an administrator"}), 503
    if submission.status not in VERIFICATION_STATES:
        raise RuntimeError("Verification provider returned an unsupported status")
    db = get_db()
    now = utcnow()
    db.execute(
        """UPDATE users SET verification_status=?,verification_submitted_at=?,
           verification_review_notes=NULL WHERE id=?""",
        (submission.status, now, user["id"]),
    )
    audit_and_commit(db, user["id"], "partner_verification_submitted", "user", user["id"])
    return jsonify({"status": submission.status}), 202


@app.get("/api/public/alerts")
def public_alerts():
    now = utcnow()
    rows = get_db().execute(
        """SELECT a.*, u.name AS partner_name FROM alerts a
           JOIN users u ON u.id=a.ngo_id
           WHERE a.blocked=0 AND a.archived=0 AND u.verified=1 AND u.blocked=0
             AND (u.verification_expires_at IS NULL OR u.verification_expires_at > ?)
             AND (a.expires_at IS NULL OR a.expires_at > ?)
           ORDER BY a.created_at DESC LIMIT 3""",
        (now, now),
    ).fetchall()
    return jsonify({"alerts": [json_row(row) for row in rows]})


@app.get("/api/public/shelters")
def public_shelters():
    city = request.args.get("city", "").strip()
    women_safe = request.args.get("women_safe") == "1"
    family_friendly = request.args.get("family_friendly") == "1"
    where = ["s.blocked=0", "s.closed=0", "s.verified=1", "u.verified=1", "u.blocked=0",
             "(u.verification_expires_at IS NULL OR u.verification_expires_at>?)"]
    params = [utcnow()]
    if city:
        where.append("LOWER(s.city) LIKE LOWER(?)")
        params.append(f"%{city}%")
    if women_safe:
        where.append("s.women_safe=1")
    if family_friendly:
        where.append("s.family_friendly=1")
    rows = get_db().execute(
        f"""SELECT s.id,s.name,s.city,s.area,s.beds_available,s.women_safe,
                   s.family_friendly,s.verified,s.updated_at,
                   COALESCE(ROUND(AVG(r.stars),1),0) AS rating,
                   COUNT(r.id) AS rating_count
            FROM shelters s JOIN users u ON u.id=s.ngo_id
            LEFT JOIN ratings r ON r.listing_type='shelter' AND r.listing_id=s.id
            WHERE {' AND '.join(where)}
            GROUP BY s.id ORDER BY s.verified DESC,s.beds_available DESC,s.updated_at DESC""",
        params,
    ).fetchall()
    return jsonify({"shelters": [json_row(row) for row in rows]})


@app.get("/api/public/services")
def public_services():
    city = request.args.get("city", "").strip()
    category = request.args.get("category", "").strip()
    where = ["s.blocked=0", "s.closed=0", "s.verified=1", "u.verified=1", "u.blocked=0",
             "(u.verification_expires_at IS NULL OR u.verification_expires_at>?)"]
    params = [utcnow()]
    if city:
        where.append("LOWER(city) LIKE LOWER(?)")
        params.append(f"%{city}%")
    if category:
        where.append("LOWER(category)=LOWER(?)")
        params.append(category)
    rows = get_db().execute(
        f"""SELECT s.id,s.name,s.category,s.city,s.opening_hours,s.contact,s.updated_at
            FROM services s JOIN users u ON u.id=s.ngo_id
            WHERE {' AND '.join(where)} ORDER BY s.updated_at DESC""",
        params,
    ).fetchall()
    return jsonify({"services": [json_row(row) for row in rows]})


@app.get("/api/public/accommodations")
def public_accommodations():
    city = request.args.get("city", "").strip()
    where = ["a.blocked=0", "a.closed=0", "a.verified=1", "u.verified=1", "u.blocked=0",
             "a.rooms_available > 0", "(u.verification_expires_at IS NULL OR u.verification_expires_at>?)"]
    params = [utcnow()]
    if city:
        where.append("LOWER(a.city) LIKE LOWER(?)")
        params.append(f"%{city}%")
    rows = get_db().execute(
        f"""SELECT a.id,a.city,a.area,a.rooms_available,a.women_only,a.description,a.updated_at
            FROM accommodations a JOIN users u ON u.id=a.host_id
            WHERE {' AND '.join(where)} ORDER BY a.updated_at DESC""",
        params,
    ).fetchall()
    return jsonify({"accommodations": [json_row(row) for row in rows]})


@app.post("/api/sos")
def create_sos():
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if data.get("website"):
        return jsonify({"ok": True})
    phone = data.get("phone") or ""
    if not is_valid_phone(phone):
        return jsonify({"error": "Enter a valid phone number with 7 to 15 digits"}), 400
    ip = request.remote_addr or "unknown"
    if not allow_rate_limited_attempt("sos", ip, 3, 300):
        return jsonify({"error": "Too many SOS submissions. Please call 112 if this is an emergency."}), 429
    db = get_db()
    cur = db.execute(
        """INSERT INTO help_requests(requester_id,type,message,requester_name,contact,location_text,status,is_sos,updated_at,created_at)
           VALUES(NULL,'SOS',?,?,?,?, 'Pending',1,?,?)""",
        (
            str(data.get("message") or "")[:1000],
            str(data.get("name") or "")[:120],
            str(phone)[:40],
            str(data.get("location") or "")[:300],
            utcnow(),
            utcnow(),
        ),
    )
    actor = current_user()
    audit_and_commit(
        db,
        actor["id"] if actor else None,
        "sos_created",
        "help_request",
        cur.lastrowid,
    )
    queue_configured_sos_notifications(cur.lastrowid)
    log_event(
        logging.INFO,
        "sos_created",
        "SOS request created",
        target_type="help_request",
        target_id=cur.lastrowid,
        outcome="created",
    )
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.get("/api/sos/incoming")
@role_required("NGO")
def incoming_sos(user):
    if not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    escalate_overdue_sos()
    rows = get_db().execute(
        """SELECT * FROM help_requests
           WHERE is_sos=1 AND status IN ('Pending','Accepted','Escalated')
             AND (claimed_by IS NULL OR claimed_by=?)
           ORDER BY CASE status WHEN 'Escalated' THEN 0 ELSE 1 END, created_at ASC""",
        (user["id"],),
    ).fetchall()
    private_rows = [row for row in rows if row["claimed_by"] == user["id"]]
    if private_rows:
        db = get_db()
        for row in private_rows:
            audit(user["id"], "sos_details_accessed", "help_request", row["id"])
        db.commit()
    return jsonify({
        "requests": [
            protected_sos(row, include_private=row["claimed_by"] == user["id"])
            for row in rows
        ]
    })


@app.get("/api/admin/sos")
@role_required("ADMIN")
def admin_sos(user):
    escalate_overdue_sos()
    db = get_db()
    rows = db.execute(
        """SELECT * FROM help_requests
           WHERE is_sos=1 AND status IN ('Pending','Accepted','Escalated')
           ORDER BY CASE status WHEN 'Escalated' THEN 0 ELSE 1 END, created_at ASC"""
    ).fetchall()
    escalated_rows = [row for row in rows if row["status"] == "Escalated"]
    for row in escalated_rows:
        audit(user["id"], "sos_details_accessed", "help_request", row["id"])
    if escalated_rows:
        db.commit()
    return jsonify({
        "requests": [
            protected_sos(row, include_private=row["status"] == "Escalated")
            for row in rows
        ]
    })


@app.get("/api/admin/notifications/failed")
@role_required("ADMIN")
def failed_emergency_notifications(user):
    rows = get_db().execute(
        """SELECT id,request_id,channel,status,attempt_count,last_error_code,
                  next_attempt_at,last_attempt_at,created_at,updated_at
           FROM emergency_notifications WHERE status IN ('Failed','Retried')
           ORDER BY updated_at DESC"""
    ).fetchall()
    return jsonify({"notifications": [json_row(row) for row in rows]})


@app.post("/api/admin/notifications/<int:notification_id>/retry")
@role_required("ADMIN")
def retry_emergency_notification(user, notification_id):
    denied = require_csrf()
    if denied:
        return denied
    db = get_db()
    row = db.execute(
        """SELECT id,request_id,channel,status,attempt_count,next_attempt_at
           FROM emergency_notifications WHERE id=?""",
        (notification_id,),
    ).fetchone()
    if not row:
        return jsonify({"error": "Notification not found"}), 404
    if row["status"] not in ("Queued", "Failed", "Retried"):
        return jsonify({"error": "Notification is not retryable"}), 409
    channel_env = row["channel"].upper().replace(" ", "_")
    recipient = os.getenv(f"WARBRIDGE_EMERGENCY_{channel_env}_RECIPIENT", "").strip()
    if not recipient:
        return jsonify({"error": "No recipient is configured for this notification channel"}), 503
    if row["next_attempt_at"] and row["next_attempt_at"] > utcnow():
        return jsonify({"error": "Notification retry is not due yet"}), 409
    try:
        status = attempt_emergency_notification(row, recipient, retry=row["attempt_count"] > 0)
    except NotificationProviderDisabledError:
        return jsonify({"error": "Emergency notification provider is disabled"}), 503
    audit_and_commit(db, user["id"], "emergency_notification_retry", "emergency_notification", notification_id)
    return jsonify({"status": status, "attempt_count": row["attempt_count"] + 1})


@app.post("/api/sos/<int:request_id>/claim")
@role_required("NGO")
def claim_sos(user, request_id):
    denied = require_csrf()
    if denied:
        return denied
    if not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        "SELECT id,status,claimed_by FROM help_requests WHERE id=? AND is_sos=1",
        (request_id,),
    ).fetchone()
    if not row:
        db.rollback()
        return jsonify({"error": "SOS request not found"}), 404
    if row["status"] not in ("Pending", "Escalated") or row["claimed_by"] is not None:
        db.rollback()
        return jsonify({"error": "SOS request is no longer available to claim"}), 409
    now = utcnow()
    updated = db.execute(
        """UPDATE help_requests SET status='Accepted',claimed_by=?,claimed_at=?,handled_by=?,updated_at=?
           WHERE id=? AND is_sos=1 AND status IN ('Pending','Escalated') AND claimed_by IS NULL""",
        (user["id"], now, user["id"], now, request_id),
    )
    if updated.rowcount != 1:
        db.rollback()
        return jsonify({"error": "SOS request is no longer available to claim"}), 409
    audit_and_commit(db, user["id"], "sos_claimed", "help_request", request_id)
    log_event(
        logging.INFO,
        "sos_claimed",
        "SOS request claimed",
        user_id=user["id"],
        role=user["role"],
        target_type="help_request",
        target_id=request_id,
        outcome="claimed",
    )
    return jsonify({"ok": True, "status": "Accepted"})


@app.post("/api/sos/<int:request_id>/<action>")
@role_required("NGO", "ADMIN")
def update_sos(user, request_id, action):
    denied = require_csrf()
    if denied:
        return denied
    if action not in ("escalate", "resolve"):
        return jsonify({"error": "Invalid action"}), 404
    if user["role"] == "NGO" and not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        "SELECT * FROM help_requests WHERE id=? AND is_sos=1",
        (request_id,),
    ).fetchone()
    if not row:
        db.rollback()
        return jsonify({"error": "SOS request not found"}), 404
    if user["role"] == "NGO" and row["claimed_by"] != user["id"]:
        db.rollback()
        return jsonify({"error": "Only the NGO that claimed this SOS can update it"}), 403
    if row["status"] not in ("Pending", "Accepted", "Escalated"):
        db.rollback()
        return jsonify({"error": "SOS request is already closed"}), 409
    if action == "resolve" and row["status"] == "Pending":
        db.rollback()
        return jsonify({"error": "SOS request must be claimed before it can be resolved"}), 409
    now = utcnow()
    status = "Escalated" if action == "escalate" else "Resolved"
    if action == "escalate":
        db.execute(
            "UPDATE help_requests SET status=?,escalated_at=?,updated_at=? WHERE id=?",
            (status, now, now, request_id),
        )
    else:
        db.execute(
            "UPDATE help_requests SET status=?,updated_at=? WHERE id=?",
            (status, now, request_id),
        )
    audit_and_commit(db, user["id"], f"sos_{action}d", "help_request", request_id)
    log_event(
        logging.INFO,
        f"sos_{action}d",
        f"SOS request {action}d",
        user_id=user["id"],
        role=user["role"],
        target_type="help_request",
        target_id=request_id,
        action=action,
        outcome=status.lower(),
    )
    return jsonify({"ok": True, "status": status})


@app.post("/api/requests")
@role_required("DISPLACED")
def create_request(user):
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    request_type = str(data.get("type", "shelter")).strip().lower()
    shelter_id = data.get("shelter_id")
    accommodation_id = data.get("accommodation_id")
    if bool(shelter_id) == bool(accommodation_id):
        return jsonify({"error": "A shelter or accommodation is required"}), 400
    if request_type not in ("shelter", "accommodation"):
        return jsonify({"error": "Request type must be shelter or accommodation"}), 400
    db = get_db()
    if shelter_id:
        if request_type != "shelter" or not isinstance(shelter_id, int):
            return jsonify({"error": "A valid shelter ID is required"}), 400
        shelter = db.execute(
            """SELECT s.* FROM shelters s JOIN users u ON u.id=s.ngo_id
               WHERE s.id=? AND u.verified=1 AND u.blocked=0
                 AND (u.verification_expires_at IS NULL OR u.verification_expires_at>?)""",
            (shelter_id, utcnow()),
        ).fetchone()
        if not shelter or shelter["blocked"] or shelter["closed"] or not shelter["verified"]:
            return jsonify({"error": "Shelter is not available"}), 404
        if shelter["beds_available"] < 1:
            return jsonify({"error": "No beds are currently available"}), 409
        if shelter["women_safe"] and str(user["gender"]).lower() != "female":
            return jsonify({"error": "This listing is restricted to users who identified as female"}), 403
        duplicate = db.execute(
            "SELECT id FROM help_requests WHERE requester_id=? AND shelter_id=? AND status IN ('Pending','Accepted')",
            (user["id"], shelter_id),
        ).fetchone()
    else:
        if request_type != "accommodation" or not isinstance(accommodation_id, int):
            return jsonify({"error": "A valid accommodation ID is required"}), 400
        accommodation = db.execute(
            """SELECT a.* FROM accommodations a JOIN users u ON u.id=a.host_id
               WHERE a.id=? AND u.verified=1 AND u.blocked=0
                 AND (u.verification_expires_at IS NULL OR u.verification_expires_at>?)""",
            (accommodation_id, utcnow()),
        ).fetchone()
        if not accommodation or accommodation["blocked"] or not accommodation["verified"] or accommodation["closed"]:
            return jsonify({"error": "Accommodation is not available"}), 404
        if accommodation["rooms_available"] < 1:
            return jsonify({"error": "No rooms are currently available"}), 409
        if accommodation["women_only"] and str(user["gender"]).lower() != "female":
            return jsonify({"error": "This listing is restricted to users who identified as female"}), 403
        duplicate = db.execute(
            "SELECT id FROM help_requests WHERE requester_id=? AND accommodation_id=? AND status IN ('Pending','Accepted')",
            (user["id"], accommodation_id),
        ).fetchone()
    if duplicate:
        return jsonify({"error": "An active request already exists"}), 409
    cur = db.execute(
        """INSERT INTO help_requests(requester_id,type,message,contact,shelter_id,accommodation_id,status,updated_at,created_at)
           VALUES(?,?,?,?,?,?, 'Pending', ?, ?)""",
        (user["id"], request_type, str(data.get("message", ""))[:1000],
         str(data.get("contact", ""))[:40], shelter_id, accommodation_id, utcnow(), utcnow()),
    )
    audit_and_commit(db, user["id"], "request_created", "help_request", cur.lastrowid)
    return jsonify({"request": {"id": cur.lastrowid, "status": "Pending"}}), 201


@app.get("/api/requests/mine")
@role_required("DISPLACED")
def mine_requests(user):
    rows = get_db().execute(
        """SELECT r.*, s.name AS shelter_name, s.address AS shelter_address,
                  s.phone AS shelter_phone, s.area AS shelter_area,
                  a.address AS accommodation_address
           FROM help_requests r
           LEFT JOIN shelters s ON s.id=r.shelter_id
           LEFT JOIN accommodations a ON a.id=r.accommodation_id
           WHERE r.requester_id=? ORDER BY r.created_at DESC""",
        (user["id"],),
    ).fetchall()
    result = []
    for row in rows:
        item = json_row(row)
        if item["status"] != "Accepted":
            item.pop("shelter_address", None)
            item.pop("shelter_phone", None)
            item.pop("accommodation_address", None)
        result.append(item)
    return jsonify({"requests": result})


@app.post("/api/requests/<int:request_id>/cancel")
@role_required("DISPLACED")
def cancel_request(user, request_id):
    denied = require_csrf()
    if denied:
        return denied
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT * FROM help_requests WHERE id=?", (request_id,)).fetchone()
    if not row or row["requester_id"] != user["id"]:
        db.rollback()
        return jsonify({"error": "Request not found"}), 404
    if row["status"] not in ("Pending", "Accepted"):
        db.rollback()
        return jsonify({"error": "Request cannot be cancelled"}), 409
    updated = db.execute("UPDATE help_requests SET status='Cancelled',handled_by=?,updated_at=? WHERE id=? AND status IN ('Pending','Accepted')",
               (user["id"], utcnow(), request_id))
    if updated.rowcount != 1:
        db.rollback()
        return jsonify({"error": "Request cannot be cancelled"}), 409
    restore_request_capacity(db, row)
    audit_and_commit(db, user["id"], "request_cancelled", "help_request", request_id)
    return jsonify({"ok": True})


@app.get("/api/requests/incoming")
@role_required("NGO", "HOST")
def incoming_requests(user):
    if not verified_required(user):
        return jsonify({"error": "Partner verification required"}), 403
    db = get_db()
    if user["role"] == "NGO":
        rows = db.execute(
            """SELECT r.* FROM help_requests r JOIN shelters s ON s.id=r.shelter_id
               WHERE s.ngo_id=? AND r.is_sos=0 AND r.status IN ('Pending','Accepted') ORDER BY r.created_at ASC""",
            (user["id"],),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT r.* FROM help_requests r JOIN accommodations a ON a.id=r.accommodation_id
               WHERE a.host_id=? AND r.is_sos=0 AND r.status IN ('Pending','Accepted') ORDER BY r.created_at ASC""",
            (user["id"],),
        ).fetchall()
    accepted_rows = [row for row in rows if row["status"] == "Accepted"]
    if accepted_rows:
        for row in accepted_rows:
            audit(user["id"], "request_details_accessed", "help_request", row["id"])
        db.commit()
    return jsonify({"requests": [protected_request(row) for row in rows]})


def restore_request_capacity(db, row):
    if row["status"] == "Accepted" and row["shelter_id"]:
        db.execute("UPDATE shelters SET beds_available=beds_available+1,updated_at=? WHERE id=?",
                   (utcnow(), row["shelter_id"]))
    elif row["status"] == "Accepted" and row["accommodation_id"]:
        db.execute(
            """UPDATE accommodations
               SET rooms_available=CASE
                       WHEN rooms_available < rooms THEN rooms_available+1
                       ELSE rooms
                   END,updated_at=?
               WHERE id=?""",
            (utcnow(), row["accommodation_id"]),
        )


@app.post("/api/requests/<int:request_id>/<action>")
@role_required("NGO", "HOST")
def handle_request(user, request_id, action):
    denied = require_csrf()
    if denied:
        return denied
    if not verified_required(user):
        return jsonify({"error": "Verification required"}), 403
    if action not in ("accept", "reject", "complete"):
        return jsonify({"error": "Invalid action"}), 404
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT * FROM help_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        db.rollback()
        return jsonify({"error": "Request not found"}), 404
    if row["is_sos"]:
        db.rollback()
        return jsonify({"error": "SOS requests use the SOS claim and resolution workflow"}), 409
    if user["role"] == "NGO" and row["shelter_id"]:
        owned = db.execute("SELECT 1 FROM shelters WHERE id=? AND ngo_id=?", (row["shelter_id"], user["id"])).fetchone()
        if not owned:
            db.rollback()
            return jsonify({"error": "Forbidden"}), 403
    elif user["role"] == "HOST" and row["accommodation_id"]:
        owned = db.execute("SELECT 1 FROM accommodations WHERE id=? AND host_id=?", (row["accommodation_id"], user["id"])).fetchone()
        if not owned:
            db.rollback()
            return jsonify({"error": "Forbidden"}), 403
    else:
        db.rollback()
        return jsonify({"error": "Forbidden"}), 403
    valid = (
        action == "accept" and row["status"] == "Pending"
        or action == "reject" and row["status"] == "Pending"
        or action == "complete" and row["status"] == "Accepted"
    )
    if not valid:
        db.rollback()
        return jsonify({"error": "Invalid status transition"}), 409
    if action == "accept" and row["shelter_id"]:
        capacity = db.execute(
            """UPDATE shelters SET beds_available=beds_available-1,updated_at=?
               WHERE id=? AND beds_available > 0 AND verified=1 AND blocked=0 AND closed=0""",
            (utcnow(), row["shelter_id"]),
        )
        if capacity.rowcount != 1:
            db.rollback()
            return jsonify({"error": "No beds available"}), 409
    elif action == "accept" and row["accommodation_id"]:
        capacity = db.execute(
            """UPDATE accommodations SET rooms_available=rooms_available-1,updated_at=?
               WHERE id=? AND rooms_available > 0 AND verified=1 AND blocked=0 AND closed=0""",
            (utcnow(), row["accommodation_id"]),
        )
        if capacity.rowcount != 1:
            db.rollback()
            return jsonify({"error": "No rooms available"}), 409
    status = {"accept": "Accepted", "reject": "Rejected", "complete": "Completed"}[action]
    db.execute("UPDATE help_requests SET status=?,handled_by=?,updated_at=? WHERE id=?",
               (status, user["id"], utcnow(), request_id))
    if action == "complete":
        restore_request_capacity(db, row)
    audit_and_commit(db, user["id"], f"request_{action}", "help_request", request_id)
    return jsonify({"ok": True, "status": status})


@app.post("/api/shelters")
@role_required("NGO")
def create_shelter(user):
    denied = require_csrf()
    if denied:
        return denied
    if not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    data = request.get_json(silent=True) or {}
    name, city, area = str(data.get("name", "")).strip(), str(data.get("city", "")).strip(), str(data.get("area", "")).strip()
    phone = data.get("phone") or ""
    try:
        beds = int(data.get("beds_available", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "beds_available must be a number"}), 400
    if not name or not city or not area or beds < 0:
        return jsonify({"error": "Name, city, area and non-negative bed count are required"}), 400
    if not is_valid_phone(phone):
        return jsonify({"error": "Enter a valid phone number with 7 to 15 digits"}), 400
    db = get_db()
    cur = db.execute(
        """INSERT INTO shelters(ngo_id,name,city,area,address,phone,beds_available,women_safe,family_friendly,verified,blocked,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,0,0,?)""",
        (user["id"], name, city, area, str(data.get("address", ""))[:300],
         str(phone)[:40], beds, int(bool(data.get("women_safe"))),
         int(bool(data.get("family_friendly"))), utcnow()),
    )
    audit_and_commit(db, user["id"], "shelter_created", "shelter", cur.lastrowid)
    return jsonify({"id": cur.lastrowid}), 201


@app.post("/api/accommodations")
@role_required("HOST")
def create_accommodation(user):
    denied = require_csrf()
    if denied:
        return denied
    if not verified_required(user):
        return jsonify({"error": "Host verification required"}), 403
    data = request.get_json(silent=True) or {}
    city, area = str(data.get("city", "")).strip(), str(data.get("area", "")).strip()
    try:
        rooms = int(data.get("rooms", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "rooms must be a number"}), 400
    if not city or not area or rooms < 1:
        return jsonify({"error": "City, area and at least one room are required"}), 400
    db = get_db()
    cur = db.execute(
        """INSERT INTO accommodations(host_id,city,area,address,rooms,rooms_available,women_only,description,verified,blocked,closed,updated_at)
           VALUES(?,?,?,?,?,?,?,?,0,0,0,?)""",
        (user["id"], city, area, str(data.get("address", ""))[:300], rooms, rooms,
         int(bool(data.get("women_only"))), str(data.get("description", ""))[:1000], utcnow()),
    )
    audit_and_commit(db, user["id"], "accommodation_created", "accommodation", cur.lastrowid)
    return jsonify({"id": cur.lastrowid}), 201


@app.post("/api/services")
@role_required("NGO")
def create_service(user):
    denied = require_csrf()
    if denied:
        return denied
    if not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON service object is required"}), 400
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    city = str(data.get("city", "")).strip()
    if not name or not city or category not in ("Food", "Healthcare", "Medical", "Legal", "Transport", "Other"):
        return jsonify({"error": "Name, city and a supported service category are required"}), 400
    db = get_db()
    cur = db.execute(
        """INSERT INTO services(ngo_id,name,category,city,opening_hours,contact,address,verified,blocked,closed,updated_at)
           VALUES(?,?,?,?,?,?,?,0,0,0,?)""",
        (
            user["id"],
            name[:120],
            category,
            city[:100],
            str(data.get("opening_hours", ""))[:120],
            str(data.get("contact", ""))[:80],
            str(data.get("address", ""))[:300],
            utcnow(),
        ),
    )
    audit_and_commit(db, user["id"], "service_created", "service", cur.lastrowid)
    return jsonify({"id": cur.lastrowid}), 201


LISTING_FIELDS = {
    "shelter": {
        "table": "shelters",
        "owner_column": "ngo_id",
        "role": "NGO",
        "text": {"name": 120, "city": 100, "area": 120, "address": 300, "phone": 40},
        "integers": {"beds_available": 0},
        "booleans": ("women_safe", "family_friendly"),
    },
    "accommodation": {
        "table": "accommodations",
        "owner_column": "host_id",
        "role": "HOST",
        "text": {"city": 100, "area": 120, "address": 300, "description": 1000},
        "integers": {"rooms": 1},
        "booleans": ("women_only",),
    },
    "service": {
        "table": "services",
        "owner_column": "ngo_id",
        "role": "NGO",
        "text": {"name": 120, "category": 40, "city": 100, "opening_hours": 120, "contact": 80, "address": 300},
        "integers": {},
        "booleans": (),
    },
}


@app.get("/api/listings/mine")
@role_required("NGO", "HOST")
def my_listings(user):
    db = get_db()
    if user["role"] == "NGO":
        rows = []
        for listing_type, table, owner_column in (
            ("shelter", "shelters", "ngo_id"),
            ("service", "services", "ngo_id"),
        ):
            columns = (
                "id,name,city,area,address,phone,beds_available,women_safe,family_friendly,verified,blocked,closed,updated_at"
                if listing_type == "shelter"
                else "id,name,category,city,opening_hours,contact,address,verified,blocked,closed,updated_at"
            )
            result = db.execute(
                f"SELECT {columns} FROM {table} WHERE {owner_column}=?",
                (user["id"],),
            ).fetchall()
            rows.extend({**json_row(row), "listing_type": listing_type} for row in result)
    else:
        result = db.execute(
            """SELECT id,city,area,address,rooms,rooms_available,women_only,description,verified,blocked,closed,updated_at
               FROM accommodations WHERE host_id=?""",
            (user["id"],),
        ).fetchall()
        rows = [{**json_row(row), "name": row["area"], "listing_type": "accommodation"} for row in result]
    return jsonify({"listings": rows})


@app.patch("/api/listings/<listing_type>/<int:listing_id>")
@role_required("NGO", "HOST")
def update_listing(user, listing_type, listing_id):
    denied = require_csrf()
    if denied:
        return denied
    spec = LISTING_FIELDS.get(listing_type)
    if not spec or user["role"] != spec["role"]:
        return jsonify({"error": "Listing type is not available to this account"}), 404
    if not verified_required(user):
        return jsonify({"error": "Partner verification required"}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "At least one listing field is required"}), 400
    allowed = set(spec["text"]) | set(spec["integers"]) | set(spec["booleans"])
    if set(data) - allowed:
        return jsonify({"error": "Unsupported listing field"}), 400

    fields = {}
    for field, limit in spec["text"].items():
        if field in data:
            value = str(data[field]).strip()
            if field in ("name", "city", "area", "category") and not value:
                return jsonify({"error": f"{field} cannot be empty"}), 400
            if field == "phone" and not is_valid_phone(value):
                return jsonify({"error": "Enter a valid phone number with 7 to 15 digits"}), 400
            if field == "category" and value not in ("Food", "Healthcare", "Medical", "Legal", "Transport", "Other"):
                return jsonify({"error": "Unsupported service category"}), 400
            fields[field] = value[:limit]
    for field, minimum in spec["integers"].items():
        if field in data:
            value = data[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                return jsonify({"error": f"{field} must be an integer of at least {minimum}"}), 400
            fields[field] = value
    for field in spec["booleans"]:
        if field in data:
            if not isinstance(data[field], bool):
                return jsonify({"error": f"{field} must be true or false"}), 400
            fields[field] = int(data[field])

    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    owner_column = spec["owner_column"]
    row = db.execute(
        f"SELECT * FROM {spec['table']} WHERE id=? AND {owner_column}=?",
        (listing_id, user["id"]),
    ).fetchone()
    if not row:
        db.rollback()
        return jsonify({"error": "Listing not found"}), 404
    if listing_type == "accommodation" and "rooms" in fields:
        occupied = row["rooms"] - row["rooms_available"]
        if fields["rooms"] < occupied:
            db.rollback()
            return jsonify({"error": "Rooms cannot be reduced below current accepted stays"}), 409
        fields["rooms_available"] = fields["rooms"] - occupied
    fields["updated_at"] = utcnow()
    assignments = ",".join(f"{field}=?" for field in fields)
    db.execute(
        f"UPDATE {spec['table']} SET {assignments} WHERE id=?",
        (*fields.values(), listing_id),
    )
    audit_and_commit(db, user["id"], f"{listing_type}_updated", listing_type, listing_id)
    return jsonify({"ok": True})


@app.post("/api/listings/<listing_type>/<int:listing_id>/<action>")
@role_required("NGO", "HOST")
def change_listing_status(user, listing_type, listing_id, action):
    denied = require_csrf()
    if denied:
        return denied
    spec = LISTING_FIELDS.get(listing_type)
    if not spec or user["role"] != spec["role"] or action not in ("close", "reopen"):
        return jsonify({"error": "Invalid listing action"}), 404
    if not verified_required(user):
        return jsonify({"error": "Partner verification required"}), 403
    db = get_db()
    row = db.execute(
        f"SELECT id FROM {spec['table']} WHERE id=? AND {spec['owner_column']}=?",
        (listing_id, user["id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "Listing not found"}), 404
    closed = int(action == "close")
    db.execute(
        f"UPDATE {spec['table']} SET closed=?,updated_at=? WHERE id=?",
        (closed, utcnow(), listing_id),
    )
    audit_and_commit(db, user["id"], f"{listing_type}_{action}d", listing_type, listing_id)
    return jsonify({"ok": True, "closed": bool(closed)})


@app.post("/api/alerts")
@role_required("NGO", "ADMIN")
def create_alert(user):
    denied = require_csrf()
    if denied:
        return denied
    if user["role"] == "NGO" and not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON alert object is required"}), 400
    title, message = str(data.get("title", "")).strip(), str(data.get("message", "")).strip()
    alert_type = str(data.get("type", "Warning")).strip()
    if not title or not message or alert_type not in ("Food", "Shelter", "Medical", "Warning"):
        return jsonify({"error": "Title, message and a valid alert type are required"}), 400
    expires_at = parse_expiry(data.get("expires_at"))
    if expires_at is False:
        return jsonify({"error": "expires_at must be a valid ISO-8601 timestamp with a timezone"}), 400
    if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        return jsonify({"error": "expires_at must be in the future"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO alerts(ngo_id,title,message,type,expires_at,blocked,updated_at,created_at) VALUES(?,?,?,?,?,0,?,?)",
        (user["id"], title[:200], message[:2000], alert_type, expires_at, utcnow(), utcnow()),
    )
    audit_and_commit(db, user["id"], "alert_created", "alert", cur.lastrowid)
    return jsonify({"id": cur.lastrowid}), 201


@app.get("/api/alerts/mine")
@role_required("NGO")
def my_alerts(user):
    rows = get_db().execute(
        "SELECT id,title,message,type,expires_at,archived,updated_at,created_at FROM alerts WHERE ngo_id=? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    return jsonify({"alerts": [json_row(row) for row in rows]})


@app.patch("/api/alerts/<int:alert_id>")
@role_required("NGO", "ADMIN")
def update_alert(user, alert_id):
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data or set(data) - {"title", "message", "type", "expires_at"}:
        return jsonify({"error": "Provide supported alert fields to update"}), 400
    db = get_db()
    row = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row or user["role"] != "ADMIN" and row["ngo_id"] != user["id"]:
        return jsonify({"error": "Alert not found"}), 404
    if user["role"] == "NGO" and not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    fields = {}
    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            return jsonify({"error": "Title cannot be empty"}), 400
        fields["title"] = title[:200]
    if "message" in data:
        message = str(data["message"]).strip()
        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400
        fields["message"] = message[:2000]
    if "type" in data:
        if data["type"] not in ("Food", "Shelter", "Medical", "Warning"):
            return jsonify({"error": "Invalid alert type"}), 400
        fields["type"] = data["type"]
    if "expires_at" in data:
        expires_at = parse_expiry(data["expires_at"])
        if expires_at is False:
            return jsonify({"error": "expires_at must be a valid ISO-8601 timestamp with a timezone"}), 400
        if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
            return jsonify({"error": "expires_at must be in the future"}), 400
        fields["expires_at"] = expires_at
    fields["updated_at"] = utcnow()
    assignments = ",".join(f"{field}=?" for field in fields)
    db.execute(f"UPDATE alerts SET {assignments} WHERE id=?", (*fields.values(), alert_id))
    audit_and_commit(db, user["id"], "alert_updated", "alert", alert_id)
    return jsonify({"ok": True})


@app.post("/api/alerts/<int:alert_id>/archive")
@role_required("NGO", "ADMIN")
def archive_alert(user, alert_id):
    denied = require_csrf()
    if denied:
        return denied
    db = get_db()
    row = db.execute("SELECT ngo_id FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row or user["role"] != "ADMIN" and row["ngo_id"] != user["id"]:
        return jsonify({"error": "Alert not found"}), 404
    if user["role"] == "NGO" and not verified_required(user):
        return jsonify({"error": "NGO verification required"}), 403
    db.execute("UPDATE alerts SET archived=1,updated_at=? WHERE id=?", (utcnow(), alert_id))
    audit_and_commit(db, user["id"], "alert_archived", "alert", alert_id)
    return jsonify({"ok": True})


@app.post("/api/reports")
@role_required("DISPLACED", "HOST", "NGO", "ADMIN")
def create_report(user):
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    listing_type = str(data.get("listing_type", "")).strip()
    listing_id = data.get("listing_id")
    reason = str(data.get("reason", "")).strip()
    if listing_type not in ("shelter", "accommodation", "service") or not isinstance(listing_id, int):
        return jsonify({"error": "Valid listing_type and listing_id are required"}), 400
    if len(reason) < 5:
        return jsonify({"error": "Reason must be at least 5 characters"}), 400
    db = get_db()
    table = {"shelter": "shelters", "accommodation": "accommodations", "service": "services"}[listing_type]
    target = db.execute(f"SELECT id,blocked FROM {table} WHERE id=?", (listing_id,)).fetchone()
    if not target or target["blocked"]:
        return jsonify({"error": "Listing does not exist or is not reportable"}), 404
    try:
        cur = db.execute(
            "INSERT INTO reports(reporter_id,listing_type,listing_id,reason,status,updated_at,created_at) VALUES(?,?,?,?, 'Open', ?, ?)",
            (user["id"], listing_type, listing_id, reason[:1000], utcnow(), utcnow()),
        )
    except DatabaseIntegrityError:
        db.rollback()
        return jsonify({"error": "You have already reported this listing"}), 409
    audit_and_commit(db, user["id"], "listing_reported", listing_type, listing_id)
    log_event(
        logging.INFO,
        "report_submitted",
        "Listing report submitted",
        user_id=user["id"],
        target_type=listing_type,
        target_id=listing_id,
        outcome="created",
    )
    return jsonify({"id": cur.lastrowid}), 201


@app.post("/api/ratings")
@role_required("DISPLACED")
def create_rating(user):
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    listing_type = str(data.get("listing_type", "")).strip()
    listing_id = data.get("listing_id")
    try:
        stars = int(data.get("stars", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "stars must be a number"}), 400
    if listing_type not in ("shelter", "accommodation", "service") or not isinstance(listing_id, int) or not 1 <= stars <= 5:
        return jsonify({"error": "Valid listing and 1 to 5 stars are required"}), 400
    if listing_type == "service":
        return jsonify({"error": "Service ratings are unavailable until completed service use can be verified"}), 403
    db = get_db()
    if listing_type == "shelter":
        completed = db.execute(
            "SELECT id FROM help_requests WHERE requester_id=? AND shelter_id=? AND status='Completed'",
            (user["id"], listing_id),
        ).fetchone()
    elif listing_type == "accommodation":
        completed = db.execute(
            "SELECT id FROM help_requests WHERE requester_id=? AND accommodation_id=? AND status='Completed'",
            (user["id"], listing_id),
        ).fetchone()
    if not completed:
        return jsonify({"error": "Ratings require a completed request"}), 403
    db.execute(
        """INSERT INTO ratings(user_id,listing_type,listing_id,stars,comment,updated_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(user_id,listing_type,listing_id) DO UPDATE SET stars=excluded.stars,comment=excluded.comment,updated_at=excluded.updated_at""",
        (user["id"], listing_type, listing_id, stars, str(data.get("comment", ""))[:1000], utcnow()),
    )
    audit_and_commit(db, user["id"], "rating_submitted", listing_type, listing_id)
    return jsonify({"ok": True})


@app.get("/api/ratings/mine")
@role_required("DISPLACED")
def my_ratings(user):
    rows = get_db().execute(
        "SELECT listing_type,listing_id,stars,comment,updated_at FROM ratings WHERE user_id=?",
        (user["id"],),
    ).fetchall()
    return jsonify({"ratings": [json_row(row) for row in rows]})


@app.get("/api/admin/verifications")
@role_required("ADMIN")
def admin_verifications(user):
    db = get_db()
    now = utcnow()
    expired = db.execute(
        """SELECT id FROM users WHERE role IN ('HOST','NGO') AND verified=1
           AND verification_expires_at IS NOT NULL AND verification_expires_at<=?
           AND verification_status='Approved'""",
        (now,),
    ).fetchall()
    for row in expired:
        db.execute(
            "UPDATE users SET verified=0,verification_status='Expired' WHERE id=?",
            (row["id"],),
        )
        audit(user["id"], "partner_verification_expired", "user", row["id"])
    if expired:
        db.commit()
    rows = get_db().execute(
        """SELECT id,name,email,role,verified,verification_status,
                  verification_review_notes,verification_submitted_at,
                  verification_reviewed_at,verification_expires_at,created_at
           FROM users
           WHERE role IN ('HOST','NGO') AND blocked=0
             AND verified=0
           ORDER BY created_at DESC""",
    ).fetchall()
    return jsonify({"users": [json_row(row) for row in rows]})


def admin_listing_rows(condition):
    specifications = (
        ("shelter", "shelters", "name", "ngo_id"),
        ("accommodation", "accommodations", "city", "host_id"),
        ("service", "services", "name", "ngo_id"),
    )
    results = []
    for listing_type, table, label_column, owner_column in specifications:
        rows = get_db().execute(
            f"""SELECT l.id,l.{label_column} AS label,l.updated_at,u.name AS owner_name
                FROM {table} l JOIN users u ON u.id=l.{owner_column}
                WHERE {condition} ORDER BY l.updated_at DESC"""
        ).fetchall()
        results.extend(
            {**json_row(row), "listing_type": listing_type}
            for row in rows
        )
    return results


@app.get("/api/admin/listings/pending")
@role_required("ADMIN")
def pending_listings(user):
    return jsonify({"listings": admin_listing_rows("l.verified=0 AND l.blocked=0")})


@app.get("/api/admin/listings/blocked")
@role_required("ADMIN")
def blocked_listings(user):
    return jsonify({"listings": admin_listing_rows("l.blocked=1")})


@app.get("/api/admin/reports")
@role_required("ADMIN")
def admin_reports(user):
    rows = get_db().execute(
        "SELECT id,reporter_id,listing_type,listing_id,reason,status,updated_at,created_at FROM reports WHERE status='Open' ORDER BY created_at ASC"
    ).fetchall()
    return jsonify({"reports": [json_row(row) for row in rows]})


@app.get("/api/admin/analytics")
@role_required("ADMIN")
def admin_analytics(user):
    db = get_db()
    role_counts = {role: 0 for role in ("DISPLACED", "HOST", "NGO", "ADMIN")}
    for row in db.execute("SELECT role,COUNT(*) AS count FROM users GROUP BY role"):
        role_counts[row["role"]] = row["count"]

    partner_counts = {
        role: {"verified": 0, "pending": 0}
        for role in ("NGO", "HOST")
    }
    for row in db.execute(
        """SELECT role,verified,COUNT(*) AS count FROM users
           WHERE role IN (?,?) AND blocked=? GROUP BY role,verified""",
        ("NGO", "HOST", 0),
    ):
        partner_counts[row["role"]]["verified" if row["verified"] else "pending"] = row["count"]

    request_status = {
        status: 0
        for status in ("pending", "accepted", "completed", "rejected", "cancelled")
    }
    for row in db.execute(
        """SELECT LOWER(status) AS status,COUNT(*) AS count FROM help_requests
           WHERE is_sos=? GROUP BY LOWER(status)""",
        (0,),
    ):
        if row["status"] in request_status:
            request_status[row["status"]] = row["count"]

    request_periods = {}
    if db.dialect == "postgresql":
        created_at_expression = "created_at::timestamptz"
        updated_at_expression = "updated_at::timestamptz"
        cutoff_expression = "?::timestamptz"
        sos_response_average = (
            "AVG(EXTRACT(EPOCH FROM "
            "(claimed_at::timestamptz - created_at::timestamptz)))::double precision"
        )
        sos_response_order = (
            "claimed_at::timestamptz>=created_at::timestamptz"
        )
    else:
        created_at_expression = "julianday(created_at)"
        updated_at_expression = "julianday(updated_at)"
        cutoff_expression = "julianday(?)"
        sos_response_average = (
            "AVG((julianday(claimed_at)-julianday(created_at))*86400.0)"
        )
        sos_response_order = "julianday(claimed_at)>=julianday(created_at)"

    for days in (7, 30, 90):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        row = db.execute(
            f"""SELECT
                   SUM(CASE WHEN {created_at_expression}>={cutoff_expression} THEN 1 ELSE 0 END) AS created,
                   SUM(CASE WHEN status=? AND {updated_at_expression}>={cutoff_expression} THEN 1 ELSE 0 END) AS completed
               FROM help_requests WHERE is_sos=?""",
            (cutoff, "Completed", cutoff, 0),
        ).fetchone()
        request_periods[f"last_{days}_days"] = {
            "created": row["created"] or 0,
            "completed": row["completed"] or 0,
        }

    available_beds = db.execute(
        """SELECT COALESCE(SUM(s.beds_available),0) AS count FROM shelters s
           JOIN users u ON u.id=s.ngo_id
           WHERE s.verified=? AND s.blocked=? AND s.closed=?
             AND u.verified=? AND u.blocked=?""",
        (1, 0, 0, 1, 0),
    ).fetchone()["count"]
    available_rooms = db.execute(
        """SELECT COALESCE(SUM(a.rooms_available),0) AS count FROM accommodations a
           JOIN users u ON u.id=a.host_id
           WHERE a.verified=? AND a.blocked=? AND a.closed=?
             AND u.verified=? AND u.blocked=?""",
        (1, 0, 0, 1, 0),
    ).fetchone()["count"]
    open_reports = db.execute(
        "SELECT COUNT(*) AS count FROM reports WHERE status=?",
        ("Open",),
    ).fetchone()["count"]

    blocked_listings = db.execute(
        """SELECT
               (SELECT COUNT(*) FROM shelters WHERE blocked=?)
             + (SELECT COUNT(*) FROM accommodations WHERE blocked=?)
             + (SELECT COUNT(*) FROM services WHERE blocked=?) AS count""",
        (1, 1, 1),
    ).fetchone()["count"]
    pending_listings = db.execute(
        """SELECT
               (SELECT COUNT(*) FROM shelters WHERE verified=? AND blocked=?)
             + (SELECT COUNT(*) FROM accommodations WHERE verified=? AND blocked=?)
             + (SELECT COUNT(*) FROM services WHERE verified=? AND blocked=?) AS count""",
        (0, 0, 0, 0, 0, 0),
    ).fetchone()["count"]

    unresolved_sos = db.execute(
        """SELECT COUNT(*) AS count FROM help_requests
           WHERE is_sos=? AND status IN (?,?,?)""",
        (1, "Pending", "Accepted", "Escalated"),
    ).fetchone()["count"]
    sos_response = db.execute(
        f"""SELECT {sos_response_average} AS average_seconds,
                  COUNT(*) AS response_count
           FROM help_requests
           WHERE is_sos=? AND claimed_at IS NOT NULL
             AND {sos_response_order}""",
        (1,),
    ).fetchone()

    has_activity = (
        any(role_counts[role] for role in ("DISPLACED", "HOST", "NGO"))
        or any(request_status.values())
        or available_beds > 0
        or available_rooms > 0
        or open_reports > 0
        or blocked_listings > 0
        or pending_listings > 0
        or unresolved_sos > 0
        or sos_response["response_count"] > 0
    )
    return jsonify({
        "users": {
            "total": sum(role_counts.values()),
            "by_role": role_counts,
            "partners": partner_counts,
        },
        "requests": {
            "by_status": request_status,
            "active_by_status": {
                "pending": request_status["pending"],
                "accepted": request_status["accepted"],
            },
            "periods": request_periods,
        },
        "listings": {
            "available_shelter_beds": available_beds,
            "available_accommodation_rooms": available_rooms,
            "open_reports": open_reports,
            "blocked": blocked_listings,
            "pending": pending_listings,
        },
        "sos": {
            "unresolved": unresolved_sos,
            "average_response_seconds": (
                round(sos_response["average_seconds"], 1)
                if sos_response["average_seconds"] is not None
                else None
            ),
            "response_count": sos_response["response_count"],
        },
        "has_activity": bool(has_activity),
    })


@app.post("/api/admin/listings/<listing_type>/<int:listing_id>/<action>")
@role_required("ADMIN")
def moderate_listing(user, listing_type, listing_id, action):
    denied = require_csrf()
    if denied:
        return denied
    tables = {"shelter": "shelters", "accommodation": "accommodations", "service": "services"}
    if listing_type not in tables or action not in ("approve", "block", "unblock"):
        return jsonify({"error": "Invalid listing moderation action"}), 404
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    table = tables[listing_type]
    target = db.execute(f"SELECT id FROM {table} WHERE id=?", (listing_id,)).fetchone()
    if not target:
        db.rollback()
        return jsonify({"error": "Listing not found"}), 404
    if action == "approve":
        db.execute(f"UPDATE {table} SET verified=1,updated_at=? WHERE id=?", (utcnow(), listing_id))
    else:
        db.execute(
            f"UPDATE {table} SET blocked=?,updated_at=? WHERE id=?",
            (1 if action == "block" else 0, utcnow(), listing_id),
        )
    audit_action = f"listing_{action}d" if action != "unblock" else "listing_unblocked"
    audit_and_commit(db, user["id"], audit_action, listing_type, listing_id)
    log_event(
        logging.INFO,
        "listing_moderation",
        "Listing moderation completed",
        user_id=user["id"],
        role=user["role"],
        target_type=listing_type,
        target_id=listing_id,
        action=action,
        outcome="completed",
    )
    return jsonify({"ok": True})


@app.post("/api/admin/users/<int:user_id>/verify")
@role_required("ADMIN")
def verify_user(user, user_id):
    denied = require_csrf()
    if denied:
        return denied
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=? AND role IN ('HOST','NGO')", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "Partner not found"}), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or set(data) - {"review_notes", "expires_at"}:
        return jsonify({"error": "Only review_notes and expires_at are allowed"}), 400
    notes = str(data.get("review_notes") or "").strip() or None
    if notes and len(notes) > 1000:
        return jsonify({"error": "Review notes must be 1000 characters or fewer"}), 400
    expires_at = parse_expiry(data.get("expires_at"))
    if expires_at is False:
        return jsonify({"error": "expires_at must be a valid ISO-8601 timestamp with a timezone"}), 400
    if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        return jsonify({"error": "expires_at must be in the future"}), 400
    reviewed_at = utcnow()
    db.execute(
        """UPDATE users SET verified=1,verification_status='Approved',
           verification_review_notes=?,verification_reviewed_at=?,
           verification_expires_at=? WHERE id=?""",
        (notes, reviewed_at, expires_at, user_id),
    )
    audit_and_commit(db, user["id"], "partner_verified", "user", user_id, notes)
    return jsonify({"ok": True})


@app.post("/api/admin/users/<int:user_id>/review")
@role_required("ADMIN")
def review_user_verification(user, user_id):
    denied = require_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or set(data) - {"review_notes"}:
        return jsonify({"error": "Only review_notes is allowed"}), 400
    notes = str(data.get("review_notes") or "").strip() or None
    if notes and len(notes) > 1000:
        return jsonify({"error": "Review notes must be 1000 characters or fewer"}), 400
    db = get_db()
    target = db.execute(
        "SELECT id FROM users WHERE id=? AND role IN ('HOST','NGO') AND verified=0 AND blocked=0",
        (user_id,),
    ).fetchone()
    if not target:
        return jsonify({"error": "Pending partner not found"}), 404
    db.execute(
        """UPDATE users SET verification_status='Under review',
           verification_review_notes=? WHERE id=?""",
        (notes, user_id),
    )
    audit_and_commit(db, user["id"], "partner_verification_review_started", "user", user_id, notes)
    return jsonify({"ok": True, "status": "Under review"})


@app.post("/api/admin/users/<int:user_id>/reject")
@role_required("ADMIN")
def reject_user(user, user_id):
    denied = require_csrf()
    if denied:
        return denied
    db = get_db()
    target = db.execute(
        "SELECT id FROM users WHERE id=? AND role IN ('HOST','NGO') AND verified=0",
        (user_id,),
    ).fetchone()
    if not target:
        return jsonify({"error": "Pending partner not found"}), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or set(data) - {"review_notes"}:
        return jsonify({"error": "Only review_notes is allowed"}), 400
    notes = str(data.get("review_notes") or "").strip() or None
    if notes and len(notes) > 1000:
        return jsonify({"error": "Review notes must be 1000 characters or fewer"}), 400
    db.execute(
        """UPDATE users SET blocked=1,verification_status='Rejected',
           verification_review_notes=?,verification_reviewed_at=? WHERE id=?""",
        (notes, utcnow(), user_id),
    )
    audit_and_commit(db, user["id"], "partner_rejected", "user", user_id, notes)
    log_event(
        logging.WARNING,
        "account_blocked",
        "Partner account blocked by an administrator",
        user_id=user["id"],
        role="ADMIN",
        target_type="user",
        target_id=user_id,
        action="reject",
        outcome="blocked",
    )
    return jsonify({"ok": True})


@app.post("/api/admin/reports/<int:report_id>/<action>")
@role_required("ADMIN")
def handle_report(user, report_id, action):
    denied = require_csrf()
    if denied:
        return denied
    if action not in ("block", "dismiss", "unblock"):
        return jsonify({"error": "Invalid action"}), 404
    db = get_db()
    report = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not report:
        return jsonify({"error": "Report not found"}), 404
    table = {"shelter": "shelters", "accommodation": "accommodations", "service": "services"}[report["listing_type"]]
    if action in ("block", "unblock"):
        target = db.execute(f"SELECT id FROM {table} WHERE id=?", (report["listing_id"],)).fetchone()
        if not target:
            db.rollback()
            return jsonify({"error": "Reported listing no longer exists"}), 404
        db.execute(f"UPDATE {table} SET blocked=?,updated_at=? WHERE id=?", (1 if action == "block" else 0, utcnow(), report["listing_id"]))
        if action == "block":
            db.execute("UPDATE reports SET status='Closed',admin_id=?,updated_at=? WHERE listing_type=? AND listing_id=?",
                       (user["id"], utcnow(), report["listing_type"], report["listing_id"]))
    else:
        db.execute("UPDATE reports SET status='Dismissed',admin_id=?,updated_at=? WHERE id=?",
                   (user["id"], utcnow(), report_id))
    audit_and_commit(db, user["id"], f"listing_{action}", report["listing_type"], report["listing_id"])
    log_event(
        logging.INFO,
        "report_decision",
        "Report decision completed",
        user_id=user["id"],
        role=user["role"],
        target_type=report["listing_type"],
        target_id=report["listing_id"],
        action=action,
        outcome="completed",
    )
    return jsonify({"ok": True})


@app.get("/api/admin/audit")
@role_required("ADMIN")
def audit_log(user):
    rows = get_db().execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200").fetchall()
    return jsonify({"audit": [json_row(row) for row in rows]})


if __name__ == "__main__":
    if APP_ENV != "development":
        raise RuntimeError("The Flask development server is disabled outside WARBRIDGE_ENV=development")
    app.run(host="127.0.0.1", port=5000, debug=False)
