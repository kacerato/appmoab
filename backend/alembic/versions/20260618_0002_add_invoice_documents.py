"""move invoice files to an immutable document dossier

Revision ID: 20260618_0002
Revises: 20260617_0001
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260618_0002"
down_revision: str | None = "20260617_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_documents (
            id UUID PRIMARY KEY,
            invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            document_type VARCHAR(50) NOT NULL,
            source VARCHAR(40) NOT NULL,
            object_key VARCHAR(700) NOT NULL UNIQUE,
            original_name VARCHAR(255) NOT NULL,
            mime_type VARCHAR(120) NOT NULL,
            size_bytes BIGINT NOT NULL,
            sha256 VARCHAR(64) NOT NULL,
            provider_document_id VARCHAR(160),
            metadata JSONB,
            supersedes_id UUID REFERENCES invoice_documents(id) ON DELETE SET NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_invoice_documents_invoice_type_sha256
                UNIQUE (invoice_id, document_type, sha256)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_documents_invoice_created ON invoice_documents (invoice_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_documents_customer_id ON invoice_documents (customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_documents_document_type ON invoice_documents (document_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_documents_sha256 ON invoice_documents (sha256)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoice_documents")

