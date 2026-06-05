"""Inside the Flask process, neutral core sessions must draw from the SAME
engine/pool as Flask-SQLAlchemy — not a second pool to the same DB."""


def test_core_session_adopts_flask_engine(app):
    from app.core.extensions import db
    from core.db.session import get_engine

    with app.app_context():
        assert get_engine() is db.engine
