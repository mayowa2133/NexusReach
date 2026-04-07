"""Add performance indexes and unique constraints for dedup and lookup queries."""

from alembic import op

revision = "020_add_performance_indexes"
down_revision = "019_add_linkedin_graph_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Jobs ---
    # Dedup lookups by source + external_id
    op.create_index(
        "ix_jobs_user_source_external",
        "jobs",
        ["user_id", "source", "external_id"],
        unique=False,
    )
    # Dedup lookups by source + url
    op.create_index(
        "ix_jobs_user_source",
        "jobs",
        ["user_id", "source"],
        unique=False,
    )
    # Startup filter queries
    op.create_index(
        "ix_jobs_user_stage",
        "jobs",
        ["user_id", "stage"],
        unique=False,
    )

    # --- People ---
    # Company-grouped people lookups
    op.create_index(
        "ix_persons_user_company",
        "persons",
        ["user_id", "company_id"],
        unique=False,
    )

    # --- Outreach ---
    # Filter outreach by person or job
    op.create_index(
        "ix_outreach_logs_user_person",
        "outreach_logs",
        ["user_id", "person_id"],
        unique=False,
    )
    op.create_index(
        "ix_outreach_logs_user_job",
        "outreach_logs",
        ["user_id", "job_id"],
        unique=False,
    )

    # --- Notifications ---
    # Idempotency check: notification per job + type
    op.create_index(
        "ix_notifications_user_job_type",
        "notifications",
        ["user_id", "job_id", "type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_job_type", table_name="notifications")
    op.drop_index("ix_outreach_logs_user_job", table_name="outreach_logs")
    op.drop_index("ix_outreach_logs_user_person", table_name="outreach_logs")
    op.drop_index("ix_persons_user_company", table_name="persons")
    op.drop_index("ix_jobs_user_stage", table_name="jobs")
    op.drop_index("ix_jobs_user_source", table_name="jobs")
    op.drop_index("ix_jobs_user_source_external", table_name="jobs")
