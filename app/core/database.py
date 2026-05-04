import asyncio
import logging
import socket
from typing import Any, AsyncGenerator, Optional, Union

from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql.elements import TextClause

from app.core.config import settings

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE URL HELPERS
# =========================================================

def _build_async_database_url(database_url: str) -> str:

    from urllib.parse import (
        urlencode,
        urlparse,
        parse_qs,
        urlunparse,
    )

    if database_url.startswith("postgresql+asyncpg://"):
        url = database_url

    elif database_url.startswith("postgresql://"):
        url = database_url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    elif database_url.startswith("postgres://"):
        url = database_url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    else:
        url = database_url

    parsed = urlparse(url)

    params = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    unsupported = {
        "sslmode",
        "channel_binding",
        "sslcert",
        "sslkey",
        "sslrootcert",
        "sslcrl",
        "application_name",
        "connect_timeout",
        "options",
        "keepalives",
        "keepalives_idle",
        "keepalives_interval",
        "keepalives_count",
        "target_session_attrs",
    }

    clean_params: dict[str, Any] = {}

    for key, values in params.items():

        if key in unsupported:
            continue

        clean_params[key] = values

    new_query = urlencode(
        clean_params,
        doseq=True,
    )

    sanitized_url = urlunparse(
        parsed._replace(query=new_query)
    )

    return sanitized_url


def _ensure_non_pooler_url(database_url: str) -> str:

    if "-pooler." in database_url:

        database_url = database_url.replace(
            "-pooler.",
            "."
        )

        logger.info(
            "Converted pooler URL -> direct URL"
        )

    if ":6543/" in database_url:

        database_url = database_url.replace(
            ":6543/",
            ":5432/",
        )

        logger.info(
            "Converted port 6543 -> 5432"
        )

    return database_url


DATABASE_URL = _ensure_non_pooler_url(
    settings.DATABASE_URL
)

ASYNC_DATABASE_URL = _build_async_database_url(
    DATABASE_URL
)

logger.info("Database configuration loaded")


# =========================================================
# DATABASE ENGINE
# =========================================================

engine = create_async_engine(
    ASYNC_DATABASE_URL,

    echo=False,
    future=True,

    pool_pre_ping=True,
    pool_recycle=1800,

    # Better for Neon free tier
    pool_size=3,
    max_overflow=2,
    pool_timeout=60,

    connect_args={
        "command_timeout": 60,

        # asyncpg SSL
        "ssl": True,

        "server_settings": {
            "statement_timeout": "60000",
        },
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# =========================================================
# CUSTOM EXCEPTIONS
# =========================================================

class DatabaseError(Exception):

    def __init__(
        self,
        message: str,
        *,
        detail: Optional[str] = None,
    ):
        super().__init__(message)

        self.message = message
        self.detail = detail


class DatabaseConnectionError(DatabaseError):
    pass


class DatabaseQueryError(DatabaseError):
    pass


# =========================================================
# ERROR DESCRIBER
# =========================================================

def describe_database_error(
    error: Exception,
) -> str:

    raw_message = str(error).lower()

    # Timeout
    if (
        isinstance(error, asyncio.TimeoutError)
        or "timeout" in raw_message
        or "cancellederror" in raw_message
    ):
        return (
            "Database connection timeout. "
            "Check internet connection and Neon host."
        )

    # DNS
    if (
        isinstance(error, socket.gaierror)
        or "getaddrinfo failed" in raw_message
        or "name or service not known" in raw_message
        or "temporary failure in name resolution" in raw_message
    ):
        return (
            "Database DNS issue. "
            "Check internet or Neon hostname."
        )

    # Auth
    if (
        "password authentication failed" in raw_message
        or "invalid password" in raw_message
    ):
        return "Invalid database credentials."

    # DB missing
    if (
        "database " in raw_message
        and "does not exist" in raw_message
    ):
        return "Database does not exist."

    # Refused
    if (
        "connection refused" in raw_message
        or "could not connect to server" in raw_message
    ):
        return "Database connection refused."

    # SSL
    if "ssl" in raw_message:
        return "SSL connection failed."

    return "Unexpected database error."


# =========================================================
# QUERY HELPERS
# =========================================================

def _normalize_query(
    query: Union[str, TextClause],
) -> tuple[TextClause, str]:
    """
    Accept either a raw SQL string or a pre-built TextClause.
    Returns (TextClause, display_string) so callers don't
    have to branch on the type themselves.
    """
    if isinstance(query, TextClause):
        return query, str(query)[:120]

    return text(query), query.strip()[:120]


def _is_write_query(
    query: Union[str, TextClause],
) -> bool:

    raw = str(query) if isinstance(query, TextClause) else query

    statement = raw.strip().split(maxsplit=1)

    if not statement:
        return False

    return statement[0].lower() in {
        "insert",
        "update",
        "delete",
        "create",
        "drop",
        "alter",
        "truncate",
    }


# =========================================================
# CUSTOM ROW
# =========================================================

class NeonRow:

    def __init__(
        self,
        data: dict[str, Any],
    ):
        self._data = data
        self._keys = list(data.keys())

    def __getattr__(
        self,
        key: str,
    ) -> Any:

        if key.startswith("_"):
            raise AttributeError(key)

        try:
            return self._data[key]

        except KeyError as exc:
            raise AttributeError(
                f"No column '{key}'"
            ) from exc

    def __getitem__(
        self,
        key: Any,
    ) -> Any:

        if isinstance(key, int):
            return self._data[self._keys[key]]

        return self._data[key]

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def to_dict(self):
        return self._data

    def __repr__(self) -> str:
        return f"NeonRow({self._data})"


# =========================================================
# CUSTOM RESULT
# =========================================================

class NeonResult:

    def __init__(
        self,
        rows: list[NeonRow],
    ):
        self._rows = rows

    def fetchall(self) -> list[NeonRow]:
        return self._rows

    def fetchone(self) -> Optional[NeonRow]:

        if self._rows:
            return self._rows[0]

        return None

    def scalar(self) -> Optional[Any]:

        row = self.fetchone()

        if row is None:
            return None

        return row[0]

    def scalar_one_or_none(
        self,
    ) -> Optional[Any]:
        return self.scalar()

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)


# =========================================================
# DATABASE SESSION WRAPPER
# =========================================================

class NeonHTTPSession:

    def __init__(
        self,
        session: Optional[AsyncSession] = None,
    ):
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        try:

            if exc:
                await self.rollback()

            else:
                await self.commit()

        finally:
            await self.close()

    async def execute(
        self,
        query: Union[str, TextClause],
        params: Optional[dict[str, Any]] = None,
    ) -> NeonResult:

        own_session = self._session is None

        session = (
            self._session
            or AsyncSessionLocal()
        )

        # Normalize: works whether caller passes a plain
        # string or an already-wrapped text() / TextClause.
        query_text, query_display = _normalize_query(query)

        try:

            logger.info(
                f"Executing query: {query_display}"
            )

            result = await session.execute(
                query_text,
                params or {},
            )

            rows = []

            try:

                rows = [
                    NeonRow(dict(row))
                    for row in result.mappings().all()
                ]

            except Exception:
                rows = []

            return NeonResult(rows)

        except IntegrityError as exc:

            if own_session:
                await session.rollback()

            logger.exception(
                f"Integrity error in query: {query_display}"
            )

            raise DatabaseQueryError(
                "Database constraint error.",
                detail=str(exc),
            ) from exc

        except (
            OperationalError,
            DBAPIError,
            SQLAlchemyError,
            asyncio.TimeoutError,
            socket.gaierror,
        ) as exc:

            if own_session:
                await session.rollback()

            logger.exception(
                f"Database connection/query error: {query_display}"
            )

            raise DatabaseConnectionError(
                describe_database_error(exc),
                detail=str(exc),
            ) from exc

        finally:

            if own_session:
                await session.close()

    async def fetchall(
        self,
        query: Union[str, TextClause],
        params: Optional[dict[str, Any]] = None,
    ) -> list[NeonRow]:

        result = await self.execute(
            query,
            params,
        )

        return result.fetchall()

    async def fetchone(
        self,
        query: Union[str, TextClause],
        params: Optional[dict[str, Any]] = None,
    ) -> Optional[NeonRow]:

        result = await self.execute(
            query,
            params,
        )

        return result.fetchone()

    async def commit(self) -> None:

        if self._session is not None:

            try:
                await self._session.commit()

            except Exception:
                logger.exception(
                    "Commit failed"
                )
                raise

    async def rollback(self) -> None:

        if self._session is not None:

            try:
                await self._session.rollback()

            except Exception:
                logger.exception(
                    "Rollback failed"
                )

    async def close(self) -> None:

        if self._session is not None:

            try:
                await self._session.close()

            except Exception:
                logger.exception(
                    "Session close failed"
                )


# =========================================================
# DEPENDENCIES
# =========================================================

async def get_db() -> AsyncGenerator[
    NeonHTTPSession,
    None,
]:

    async with AsyncSessionLocal() as session:

        db = NeonHTTPSession(session)

        try:
            yield db

        except Exception:

            await db.rollback()
            raise

        finally:
            await db.close()


async def get_async_session() -> AsyncGenerator[
    AsyncSession,
    None,
]:

    async with AsyncSessionLocal() as session:
        yield session


# =========================================================
# DATABASE HEALTH CHECK
# =========================================================

async def check_database_connection(
) -> tuple[bool, str]:

    try:

        async with engine.connect() as connection:

            result = await asyncio.wait_for(
                connection.execute(
                    text("SELECT 1 AS health")
                ),
                timeout=30,
            )

            value = result.scalar_one_or_none()

            if value == 1:

                return (
                    True,
                    "Database connected successfully.",
                )

            return (
                False,
                "Database responded unexpectedly.",
            )

    except Exception as exc:

        logger.exception(
            "Database health check failed"
        )

        return (
            False,
            describe_database_error(exc),
        )


# =========================================================
# INIT MODELS
# =========================================================

async def init_models() -> None:
    """
    Alembic use kar rahe ho to
    empty rehne do.
    """
    pass