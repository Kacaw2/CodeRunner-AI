"""Thread-local DB session context for agent tools.

When running inside Agent Host, the worker sets _current_session before
invoking agents. Tools read it to avoid Flask-SQLAlchemy dependency.
When running inside Flask (fallback), _current_session is None and tools
fall back to Model.query (Flask-SQLAlchemy).
"""

import contextvars

_current_session: contextvars.ContextVar = contextvars.ContextVar(
    "db_session", default=None
)


def get_current_session():
    return _current_session.get()


def set_current_session(session):
    return _current_session.set(session)
