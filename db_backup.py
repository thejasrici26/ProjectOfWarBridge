import argparse
import base64
import logging
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from structured_logging import JsonLogFormatter, LOG_LEVELS


_BACKUP_MAGIC = b"WBK1"
_NONCE_LENGTH = 12
_TAG_LENGTH = 16
_CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger("warbridge.backup")


def _validate_database(path):
    with closing(sqlite3.connect(path)) as connection:
        results = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if results != ["ok"]:
        raise ValueError(f"Database integrity check failed for {path}: {'; '.join(results)}")


def _temporary_path(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(name)


def _same_file(path_a, path_b):
    if path_a == path_b:
        return True
    return path_a.exists() and path_b.exists() and os.path.samefile(path_a, path_b)


def _copy_database(source, destination):
    with closing(sqlite3.connect(source)) as source_connection, closing(
        sqlite3.connect(destination)
    ) as destination_connection:
        source_connection.backup(destination_connection)
    _validate_database(destination)
    if os.name != "nt":
        os.chmod(destination, 0o600)


def _normalize_encryption_key(key):
    if key is None:
        return None
    is_encoded_string = isinstance(key, str)
    if is_encoded_string:
        key = key.encode("ascii")
    if not is_encoded_string and len(key) == 32:
        return key
    try:
        decoded = base64.b64decode(key, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError(
            "WARBRIDGE_BACKUP_ENCRYPTION_KEY must be a 32-byte URL-safe base64 key"
        ) from error
    if len(decoded) != 32:
        raise ValueError(
            "WARBRIDGE_BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes"
        )
    return decoded


def _key_from_environment():
    key = os.getenv("WARBRIDGE_BACKUP_ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "Encrypted backup requested but WARBRIDGE_BACKUP_ENCRYPTION_KEY is not set"
        )
    return _normalize_encryption_key(key)


def _encrypt_file(source, destination, key):
    nonce = os.urandom(_NONCE_LENGTH)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    with source.open("rb") as source_file, destination.open("wb") as target_file:
        target_file.write(_BACKUP_MAGIC + nonce)
        while chunk := source_file.read(_CHUNK_SIZE):
            target_file.write(encryptor.update(chunk))
        target_file.write(encryptor.finalize())
        target_file.write(encryptor.tag)
        target_file.flush()
        os.fsync(target_file.fileno())


def _decrypt_file(source, destination, key):
    size = source.stat().st_size
    header_length = len(_BACKUP_MAGIC) + _NONCE_LENGTH
    if size < header_length + _TAG_LENGTH:
        raise ValueError(f"Encrypted backup is truncated: {source}")

    with source.open("rb") as source_file:
        header = source_file.read(header_length)
        if header[:len(_BACKUP_MAGIC)] != _BACKUP_MAGIC:
            raise ValueError(f"Unrecognized encrypted backup format: {source}")
        nonce = header[len(_BACKUP_MAGIC):]
        source_file.seek(size - _TAG_LENGTH)
        tag = source_file.read(_TAG_LENGTH)
        source_file.seek(header_length)
        encrypted_length = size - header_length - _TAG_LENGTH
        decryptor = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce, tag),
        ).decryptor()

        try:
            with destination.open("wb") as target_file:
                remaining = encrypted_length
                while remaining:
                    chunk = source_file.read(min(_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError(f"Encrypted backup is truncated: {source}")
                    remaining -= len(chunk)
                    target_file.write(decryptor.update(chunk))
                target_file.write(decryptor.finalize())
                target_file.flush()
                os.fsync(target_file.fileno())
        except InvalidTag as error:
            destination.unlink(missing_ok=True)
            raise ValueError(
                "Backup authentication failed; the encryption key is wrong or the file is corrupted"
            ) from error
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def _is_encrypted(path):
    with path.open("rb") as backup_file:
        return backup_file.read(len(_BACKUP_MAGIC)) == _BACKUP_MAGIC


def _timestamped_path(directory, encrypted=False, prefix="warbridge-backup"):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = ".sqlite3.enc" if encrypted else ".sqlite3"
    base = directory / f"{prefix}-{timestamp}"
    candidate = base.with_name(f"{base.name}{suffix}")
    counter = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{counter:02d}{suffix}")
        counter += 1
    return candidate


def _publish_new_file(temporary, destination):
    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise FileExistsError(f"Backup already exists: {destination}") from None
    temporary.unlink()


def verify_backup_restore(backup, encryption_key=None):
    backup = Path(backup).resolve()
    if not backup.is_file():
        raise FileNotFoundError(f"Backup does not exist: {backup}")

    key = _normalize_encryption_key(encryption_key)
    with TemporaryDirectory(prefix="warbridge-restore-test-") as directory:
        work_directory = Path(directory)
        source = backup
        if _is_encrypted(backup):
            if key is None:
                key = _key_from_environment()
            source = work_directory / "decrypted.sqlite3"
            _decrypt_file(backup, source, key)
        restored = work_directory / "restored.sqlite3"
        _copy_database(source, restored)
    logger.info(
        "Backup restore verification passed",
        extra={"event": "backup_restore_verification_passed"},
    )
    return True


def backup_database(source, destination=None, encryption_key=None):
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")

    key = _normalize_encryption_key(encryption_key)
    if destination is None:
        backup_directory = _configured_backup_directory(source)
        destination = _timestamped_path(backup_directory, encrypted=key is not None)
    destination = Path(destination).resolve()
    if _same_file(source, destination):
        raise ValueError("Backup destination must differ from the live database")
    if destination.exists():
        raise FileExistsError(f"Backup already exists: {destination}")

    temporary_database = _temporary_path(destination)
    temporary_output = None
    try:
        _copy_database(source, temporary_database)
        output = temporary_database
        if key is not None:
            temporary_output = _temporary_path(destination)
            _encrypt_file(temporary_database, temporary_output, key)
            output = temporary_output

        _publish_new_file(output, destination)
        try:
            verify_backup_restore(destination, key)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        logger.info(
            "Backup created and verified",
            extra={"event": "backup_created"},
        )
        return destination
    finally:
        temporary_database.unlink(missing_ok=True)
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


def restore_database(backup, destination, confirm=False, encryption_key=None):
    if not confirm:
        raise PermissionError("Restore requires explicit confirmation")

    backup = Path(backup).resolve()
    destination = Path(destination).resolve()
    if _same_file(backup, destination):
        raise ValueError("Restore source must differ from the live database")
    if not backup.is_file():
        raise FileNotFoundError(f"Backup does not exist: {backup}")

    key = _normalize_encryption_key(encryption_key)
    temporary = _temporary_path(destination)
    safety_temporary = None
    safety_copy = None
    destination_existed = destination.exists()
    installed = False
    try:
        with TemporaryDirectory(prefix="warbridge-restore-") as directory:
            source = backup
            if _is_encrypted(backup):
                if key is None:
                    key = _key_from_environment()
                source = Path(directory) / "decrypted.sqlite3"
                _decrypt_file(backup, source, key)
            _copy_database(source, temporary)

        if destination_existed:
            safety_copy = _timestamped_path(
                destination.parent,
                prefix=f"{destination.name}.pre-restore",
            )
            safety_temporary = _temporary_path(safety_copy)
            _copy_database(destination, safety_temporary)
            _publish_new_file(safety_temporary, safety_copy)
            safety_temporary = None
            os.replace(temporary, destination)
        else:
            _publish_new_file(temporary, destination)
        installed = True
        _validate_database(destination)
        logger.info(
            "Database restore completed",
            extra={"event": "database_restore_completed"},
        )
        return destination, safety_copy
    except Exception:
        if installed:
            try:
                if safety_copy and safety_copy.exists():
                    os.replace(safety_copy, destination)
                elif not destination_existed:
                    destination.unlink(missing_ok=True)
            except OSError:
                logger.error(
                    "Could not roll back failed restore",
                    extra={
                        "event": "restore_rollback_failed",
                        "error_type": "OSError",
                    },
                )
        raise
    finally:
        temporary.unlink(missing_ok=True)
        if safety_temporary is not None:
            safety_temporary.unlink(missing_ok=True)


def cleanup_backups(directory, retention_days=30, retention_count=14, now=None):
    if retention_days < 0 or retention_count < 0:
        raise ValueError("Backup retention values must not be negative")
    if retention_days == 0 and retention_count == 0:
        raise ValueError("At least one backup retention rule must be enabled")

    directory = Path(directory).resolve()
    if not directory.is_dir():
        return []
    backups = sorted(
        (
            path
            for path in directory.glob("warbridge-backup-*.sqlite3*")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    deleted = []
    for index, path in enumerate(backups):
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        within_age = retention_days > 0 and modified >= cutoff
        within_count = retention_count > 0 and index < retention_count
        if within_age or within_count:
            continue
        path.unlink()
        deleted.append(path)
        logger.info(
            "Expired backup removed",
            extra={"event": "backup_retention_removed"},
        )
    return deleted


def _configured_backup_directory(database):
    configured = os.getenv("WARBRIDGE_BACKUP_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(database).resolve().parent / "backups"


def _selected_database_url():
    environment = os.getenv("WARBRIDGE_ENV", "production").strip().lower()
    if environment == "test":
        return os.getenv("WARBRIDGE_TEST_DATABASE_URL")
    if environment == "development":
        return (
            os.getenv("WARBRIDGE_DEVELOPMENT_DATABASE_URL")
            or os.getenv("WARBRIDGE_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
    return os.getenv("WARBRIDGE_DATABASE_URL") or os.getenv("DATABASE_URL")


def _configure_logging(backup_directory):
    level_name = os.getenv("WARBRIDGE_LOG_LEVEL", "INFO").strip().upper()
    if level_name not in LOG_LEVELS:
        raise ValueError(
            "WARBRIDGE_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
        )
    log_path = Path(
        os.getenv(
            "WARBRIDGE_BACKUP_LOG",
            str(backup_directory / "warbridge-backup.log"),
        )
    ).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = (logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(
        level=LOG_LEVELS[level_name],
        handlers=handlers,
        force=True,
    )


def _nonnegative_integer(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return number


def _retention_environment(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return _nonnegative_integer(value)
    except argparse.ArgumentTypeError as error:
        raise ValueError(f"{name} must be a non-negative integer") from error


def main():
    parser = argparse.ArgumentParser(
        description="Create, verify, retain, or restore SQLite database backups."
    )
    parser.add_argument(
        "--database",
        default=os.getenv(
            "WARBRIDGE_DB",
            str(Path(__file__).resolve().parent / "warbridge.db"),
        ),
        help="Path to the WarBridge SQLite database",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Create and verify a timestamped backup")
    backup.add_argument("--output", help="Optional explicit destination (must not exist)")
    backup.add_argument("--encrypt", action="store_true", help="Encrypt using the configured key")
    backup.add_argument(
        "--retention-days",
        type=_nonnegative_integer,
        help="Keep backups newer than this many days (default: WARBRIDGE_BACKUP_RETENTION_DAYS or 30)",
    )
    backup.add_argument(
        "--retention-count",
        type=_nonnegative_integer,
        help="Always keep this many newest backups (default: WARBRIDGE_BACKUP_RETENTION_COUNT or 14)",
    )

    verify = commands.add_parser(
        "verify",
        help="Test restoring a backup into an isolated temporary database",
    )
    verify.add_argument("--input", required=True, help="Backup to verify")

    restore = commands.add_parser("restore", help="Restore after stopping the application")
    restore.add_argument("--input", required=True, help="Source backup SQLite file")
    restore.add_argument(
        "--confirm-restore",
        action="store_true",
        help="Confirm replacing the live database",
    )
    args = parser.parse_args()

    try:
        if _selected_database_url():
            raise ValueError(
                "db_backup.py supports SQLite only; use PostgreSQL provider backup tooling"
            )
        database = Path(args.database).expanduser().resolve()
        backup_directory = _configured_backup_directory(database)
        _configure_logging(backup_directory)

        if args.command == "backup":
            key = _key_from_environment() if args.encrypt else None
            retention_days = (
                args.retention_days
                if args.retention_days is not None
                else _retention_environment("WARBRIDGE_BACKUP_RETENTION_DAYS", 30)
            )
            retention_count = (
                args.retention_count
                if args.retention_count is not None
                else _retention_environment("WARBRIDGE_BACKUP_RETENTION_COUNT", 14)
            )
            if retention_days == 0 and retention_count == 0:
                raise ValueError("At least one backup retention rule must be enabled")
            destination = (
                Path(args.output).expanduser().resolve()
                if args.output
                else _timestamped_path(
                    backup_directory,
                    encrypted=key is not None,
                )
            )
            created = backup_database(database, destination, key)
            cleanup_backups(
                backup_directory,
                retention_days=retention_days,
                retention_count=retention_count,
            )
            print(created)
            return

        if args.command == "verify":
            verify_backup_restore(args.input)
            print(f"Restore verification passed: {Path(args.input).resolve()}")
            return

        if not args.confirm_restore:
            parser.error("restore requires --confirm-restore")
        restored, safety_copy = restore_database(
            args.input,
            database,
            confirm=args.confirm_restore,
        )
        print(f"Restored {restored}")
        if safety_copy:
            print(f"Previous database preserved at {safety_copy}")
    except Exception as error:
        logger.error(
            "Backup operation failed",
            extra={
                "event": "backup_operation_failed",
                "error_type": type(error).__name__,
            },
        )
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
