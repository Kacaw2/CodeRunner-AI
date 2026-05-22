"""Migrate questions to parent problems with language variants.

Revision ID: problem_variant_schema
Revises: c3d4e5f6a7b8
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "problem_variant_schema"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def canonical_title(title):
    title = (title or "").strip()
    for suffix in (" (C)", " (c)", " - C", " - c"):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def slugify(title, fallback_id):
    import re

    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return base or f"problem-{fallback_id}"


def _column_names(connection, table_name):
    inspector = sa.inspect(connection)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    op.create_table(
        "problems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=True, server_default="easy"),
        sa.Column("points", sa.Integer(), nullable=True, server_default="10"),
        sa.Column("order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("slug", name="uq_problems_slug"),
    )
    op.create_index("ix_problems_slug", "problems", ["slug"])

    op.create_table(
        "quiz_problems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), nullable=True, server_default="10"),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"]),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.UniqueConstraint("quiz_id", "problem_id", name="unique_quiz_problem"),
    )

    op.add_column("questions", sa.Column("problem_id", sa.Integer(), nullable=True))
    op.add_column("questions", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.add_column("test_cases", sa.Column("problem_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(
        bind=connection,
        only=("questions", "test_cases", "quiz_questions", "problems", "quiz_problems"),
    )
    questions = metadata.tables["questions"]
    test_cases = metadata.tables["test_cases"]
    quiz_questions = metadata.tables.get("quiz_questions")
    problems = metadata.tables["problems"]
    quiz_problems = metadata.tables["quiz_problems"]

    question_rows = connection.execute(sa.select(questions)).mappings().all()
    grouped = {}
    for row in question_rows:
        grouped.setdefault(canonical_title(row["title"]), []).append(row)

    problem_id_by_question_id = {}
    used_slugs = set()
    now = sa.func.now()

    for _, rows in grouped.items():
        rows = sorted(rows, key=lambda item: item["id"])
        first = rows[0]
        base_slug = slugify(canonical_title(first["title"]), first["id"])
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)

        result = connection.execute(
            problems.insert().values(
                slug=slug,
                title=canonical_title(first["title"]),
                description=first["description"] or "",
                difficulty="easy",
                points=first["points"],
                order=first["order"],
                created_by=first["created_by"],
                created_at=first["created_at"],
                updated_at=now,
            )
        )
        problem_id = result.inserted_primary_key[0]

        question_ids = [row["id"] for row in rows]
        connection.execute(
            questions.update()
            .where(questions.c.id.in_(question_ids))
            .values(problem_id=problem_id, updated_at=now)
        )
        for question_id in question_ids:
            problem_id_by_question_id[question_id] = problem_id

        python_row = next(
            (row for row in rows if (row["programming_language"] or "").lower() == "python"),
            None,
        )
        selected_row = python_row or first
        duplicate_question_ids = [row["id"] for row in rows if row["id"] != selected_row["id"]]
        if duplicate_question_ids:
            connection.execute(
                test_cases.delete().where(test_cases.c.question_id.in_(duplicate_question_ids))
            )
        connection.execute(
            test_cases.update()
            .where(test_cases.c.question_id == selected_row["id"])
            .values(problem_id=problem_id)
        )

    if quiz_questions is not None:
        seen_quiz_problem = set()
        for row in connection.execute(sa.select(quiz_questions)).mappings().all():
            problem_id = problem_id_by_question_id.get(row["question_id"])
            if not problem_id:
                continue
            key = (row["quiz_id"], problem_id)
            if key in seen_quiz_problem:
                continue
            seen_quiz_problem.add(key)
            connection.execute(
                quiz_problems.insert().values(
                    quiz_id=row["quiz_id"],
                    problem_id=problem_id,
                    order=row["order"],
                    points=row["points"],
                    added_at=row["added_at"],
                )
            )

    with op.batch_alter_table("questions") as batch_op:
        batch_op.alter_column("problem_id", nullable=False)
        batch_op.drop_column("title")
        batch_op.drop_column("description")
        batch_op.drop_column("points")
        batch_op.drop_column("order")
        batch_op.drop_column("created_by")
        batch_op.create_foreign_key("fk_questions_problem", "problems", ["problem_id"], ["id"])
        batch_op.create_unique_constraint("uq_question_problem_language", ["problem_id", "programming_language"])

    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.alter_column("problem_id", nullable=False)
        batch_op.drop_column("question_id")
        batch_op.create_foreign_key("fk_test_cases_problem", "problems", ["problem_id"], ["id"])

    op.drop_table("quiz_questions")


def downgrade():
    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), server_default="10"),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
        sa.UniqueConstraint("quiz_id", "question_id", name="unique_quiz_question"),
    )
    with op.batch_alter_table("test_cases") as batch_op:
        batch_op.add_column(sa.Column("question_id", sa.Integer(), nullable=True))
        batch_op.drop_column("problem_id")
    with op.batch_alter_table("questions") as batch_op:
        batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("order", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("points", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("title", sa.String(length=200), nullable=True))
        batch_op.drop_constraint("uq_question_problem_language", type_="unique")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("problem_id")
    op.drop_table("quiz_problems")
    op.drop_index("ix_problems_slug", table_name="problems")
    op.drop_table("problems")
