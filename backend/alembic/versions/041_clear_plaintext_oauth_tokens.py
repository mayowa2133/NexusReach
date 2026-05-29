"""Clear plaintext OAuth refresh tokens.

Revision ID: 041_clear_plaintext_oauth_tokens
Revises: 040_add_target_occupations
"""

from alembic import op


revision = "041_clear_plaintext_oauth_tokens"
down_revision = "040_add_target_occupations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Force reconnect for providers that stored plaintext refresh tokens."""
    op.execute(
        """
        UPDATE user_settings
        SET gmail_refresh_token = NULL,
            gmail_connected = false
        WHERE gmail_refresh_token IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE user_settings
        SET outlook_refresh_token = NULL,
            outlook_connected = false
        WHERE outlook_refresh_token IS NOT NULL
        """
    )


def downgrade() -> None:
    """Token removal is irreversible."""
    pass
