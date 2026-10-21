"""Add two-level category hierarchy and immutable parent snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("product_categories", sa.Column("parent_category_id", mysql.BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key("fk_category_parent_site", "product_categories", "product_categories", ["parent_category_id", "site_id"], ["id", "site_id"], ondelete="RESTRICT", onupdate="RESTRICT")
    op.add_column("product_catalog_style_members", sa.Column("category_parent_snapshot", mysql.JSON(), nullable=True))

def downgrade():
    op.drop_column("product_catalog_style_members", "category_parent_snapshot")
    op.drop_constraint("fk_category_parent_site", "product_categories", type_="foreignkey")
    op.drop_column("product_categories", "parent_category_id")
