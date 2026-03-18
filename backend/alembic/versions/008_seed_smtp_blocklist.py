"""Seed smtp_domain_results with known-blocked corporate domains.

These domains are confirmed or highly likely to use Secure Email Gateways
(Proofpoint, Mimecast, Barracuda) or hardened infrastructure that makes SMTP
RCPT TO verification impossible. Pre-seeding them saves the MX lookup overhead
on first probe and immediately routes these companies to paid API fallbacks.

Blocked for 180 days — consistent with SMTP_INFRASTRUCTURE_BLOCK_TTL_DAYS.

Revision ID: 008_seed_smtp_blocklist
Revises: 007_add_smtp_domain_results
"""

from alembic import op

revision = "008_seed_smtp_blocklist"
down_revision = "007_add_smtp_domain_results"
branch_labels = None
depends_on = None

# Domains confirmed or highly likely to block SMTP verification.
# Source: MX record analysis + industry knowledge of Proofpoint/Mimecast adoption.
BLOCKED_DOMAINS = [
    # Big Tech — own hardened infrastructure or confirmed Proofpoint
    "google.com",       # Self-hosted; deeply hardened; employee SMTP probing unreliable
    "amazon.com",       # Confirmed Proofpoint customer (Fortune 100)
    "meta.com",         # Confirmed Proofpoint customer (Fortune 100)
    "microsoft.com",    # Own Exchange Online + Defender; very large tenant
    "apple.com",        # Microsoft 365 tenant; large corp configuration
    # Enterprise cloud / hardware — confirmed or likely SEG
    "nvidia.com",       # Confirmed Proofpoint (Datanyze)
    "salesforce.com",   # Confirmed Proofpoint (Fortune 500 enterprise)
    "oracle.com",       # Enterprise; Proofpoint or Mimecast
    "ibm.com",          # Microsoft 365 + Proofpoint overlay
    "intel.com",        # Enterprise SEG (Proofpoint/Mimecast)
    "cisco.com",        # IronPort (their own email security product)
    "qualcomm.com",     # Enterprise SEG
    "intuit.com",       # Confirmed Proofpoint
    "adobe.com",        # Microsoft 365 / Proofpoint
    "sap.com",          # Self-hosted enterprise SAP mail infrastructure
    # Cloudflare — uses their own Email Routing product; blocks SMTP probing
    "cloudflare.com",
    # Canadian banks — all use Microsoft 365 + enterprise SEG
    "rbc.com",
    "td.com",
    "scotiabank.com",
    "bmo.com",
    "cibc.com",
]


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Use INSERT ... ON CONFLICT DO NOTHING so re-running is safe and
    # doesn't overwrite records that already have organic probe history.
    for domain in BLOCKED_DOMAINS:
        op.execute(
            f"""
            INSERT INTO smtp_domain_results
                (id, domain, success_count, catch_all_count, blocked_count,
                 greylist_count, blocked_until, created_at, updated_at)
            VALUES (
                gen_random_uuid(),
                '{domain}',
                0, 0, 3, 0,
                CURRENT_TIMESTAMP + INTERVAL '180 days',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (domain) DO NOTHING
            """
        )


def downgrade() -> None:
    for domain in BLOCKED_DOMAINS:
        op.execute(f"DELETE FROM smtp_domain_results WHERE domain = '{domain}'")
