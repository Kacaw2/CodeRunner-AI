# app/__init__.py
import os
from flask import Flask
from app.core.config import config
from app.core.extensions import init_extensions

def create_app(config_name=None):
    # 1. Use environment variable to determine which config to use, default to config's default
    env_name = config_name or os.getenv("FLASK_ENV", "default")

    app = Flask(__name__)
    app.config.from_object(config.get(env_name, config["default"]))

    # 2. Prevent sqlite path not existing: if it's sqlite:////xxx, create the directory
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:////"):
        db_path = uri.replace("sqlite:////", "", 1)   # /opt/data/app.db
        db_dir = os.path.dirname(db_path)             # /opt/data
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    # 3. Initialize extensions (db, api, migrate...)
    init_extensions(app)

    # 4. Register blueprints
    register_blueprints(app)

    return app


def register_blueprints(app):
    from app.core.extensions import api
    
    from app.api.public.health import health_bp
    app.register_blueprint(health_bp)

    from app.api.v1.auth import bp as auth_api_bp
    api.register_blueprint(auth_api_bp)

    from app.api.v1.questions import blp as questions_blp
    from app.api.v1.questions import public_blp as questions_public_blp
    api.register_blueprint(questions_blp)
    api.register_blueprint(questions_public_blp)

    from app.api.v1.submissions import blp as submissions_blp
    api.register_blueprint(submissions_blp)

    from app.api.v1.judge import bp as judge_bp
    app.register_blueprint(judge_bp)

    from app.api.v1.grades import blp as grades_blp
    api.register_blueprint(grades_blp)

    from app.api.v1.classrooms import blp as classrooms_blp
    api.register_blueprint(classrooms_blp)

    from app.api.v1.quizzes import blp as quizzes_blp
    api.register_blueprint(quizzes_blp)

    from app.api.v1.problems import blp as problems_blp
    api.register_blueprint(problems_blp)

    from app.api.v1.teacher_stats import blp as teacher_stats_blp
    api.register_blueprint(teacher_stats_blp)

    from app.api.v1.teacher_students import blp as teacher_students_blp
    api.register_blueprint(teacher_students_blp)
    
    from app.api.v1.user_profile import blp as user_profile_blp
    api.register_blueprint(user_profile_blp)


    # === Public API Endpoints ===

    from app.api.public import public_bp
    app.register_blueprint(public_bp)
 
    from app.api.public.quizzes import public_quiz_blp
    api.register_blueprint(public_quiz_blp)

    from app.web import main_bp, auth_bp, student_bp, teacher_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(teacher_bp)

    from app.web.question import question_bp
    app.register_blueprint(question_bp)

    from app.web.submissions import submissions_web_bp
    app.register_blueprint(submissions_web_bp)

    from app.api.v1.ai import bp as ai_bp
    app.register_blueprint(ai_bp)

    from app.web.ai_chat import ai_chat_bp
    app.register_blueprint(ai_chat_bp)


# for gunicorn
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9900, debug=app.config["DEBUG"])
