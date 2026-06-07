"""FastAPI Agent Runtime.

A new async execution boundary built on the shared SQLAlchemy domain
(``domain/`` + ``core/``). It is NOT a revival of the deleted FastAPI agent
host: it imports only the domain, core, and the existing agent kernel, never
``app.core.extensions``.
"""
