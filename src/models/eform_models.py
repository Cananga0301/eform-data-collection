"""
SQLAlchemy 2.0 ORM models for the E-Form Data Collection module.

All timestamps are TIMESTAMPTZ (timezone-aware). Migrations are managed by
Alembic — never use Base.metadata.create_all() in production.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CHAR, Column, Date, ForeignKey, Index,
    Integer, SmallInteger, Text, UniqueConstraint, VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Branches
# ──────────────────────────────────────────────────────────────────────────────

class Branch(Base):
    __tablename__ = 'branches'

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)

    mappings = relationship('BranchMapping', back_populates='branch', cascade='all, delete-orphan')
    segments = relationship('Segment', back_populates='branch')
    assignments = relationship('Assignment', back_populates='branch')


class BranchMapping(Base):
    """
    Maps a normalized key → branch.
    key_type = 'xa_phuong': try this first.
    key_type = 'tinh_thanh': fallback if no xa_phuong match.
    """
    __tablename__ = 'branch_mappings'

    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey('branches.id', ondelete='CASCADE'), nullable=False)
    key_type = Column(VARCHAR(20), nullable=False)   # 'xa_phuong' | 'tinh_thanh'
    key_value = Column(Text, nullable=False)          # normalized value

    branch = relationship('Branch', back_populates='mappings')

    __table_args__ = (
        UniqueConstraint('key_type', 'key_value', name='uq_branch_mappings_key'),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Segments
# ──────────────────────────────────────────────────────────────────────────────

class Segment(Base):
    __tablename__ = 'segments'

    id = Column(Integer, primary_key=True)

    # Original display values
    tinh_thanh = Column(VARCHAR(100))
    xa_phuong = Column(Text)
    ten_duong = Column(Text)
    doan = Column(Text)           # nullable — 616 rows have no doan
    doan_key = Column(Text)       # = doan if not null, else ten_duong (original casing)

    # Normalized values for matching (diacritic-stripped, lowercased)
    tinh_thanh_norm = Column(Text)
    xa_phuong_norm = Column(Text)
    ten_duong_norm = Column(Text)
    doan_key_norm = Column(Text)

    # State land price positions (null = position does not exist for this segment)
    vt1 = Column(BigInteger)
    vt2 = Column(BigInteger)
    vt3 = Column(BigInteger)
    vt4 = Column(BigInteger)

    # A/B/C group
    nhom = Column(CHAR(1))
    nhom_manual = Column(Boolean, default=False, nullable=False)

    # Records required per position (3 if position exists, null otherwise)
    so_can_vt1 = Column(Integer)
    so_can_vt2 = Column(Integer)
    so_can_vt3 = Column(Integer)
    so_can_vt4 = Column(Integer)

    # Branch (default from mapping, can be overridden in assignment)
    branch_id = Column(Integer, ForeignKey('branches.id', ondelete='SET NULL'))

    trang_thai = Column(VARCHAR(50), default='Chưa bắt đầu')
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    branch = relationship('Branch', back_populates='segments')
    assignments = relationship('Assignment', back_populates='segment', cascade='all, delete-orphan')
    collected_records = relationship('CollectedRecord', back_populates='segment')
    verification_logs = relationship('VerificationLog', back_populates='segment', cascade='all, delete-orphan')

    __table_args__ = (
        UniqueConstraint(
            'tinh_thanh_norm', 'xa_phuong_norm', 'ten_duong_norm', 'doan_key_norm',
            name='uq_segments_norm_key',
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Assignments
# ──────────────────────────────────────────────────────────────────────────────

class Assignment(Base):
    __tablename__ = 'assignments'

    id = Column(Integer, primary_key=True)
    segment_id = Column(Integer, ForeignKey('segments.id', ondelete='CASCADE'), nullable=False, unique=True)
    phu_trach = Column(Text)
    deadline = Column(Date)
    branch_id = Column(Integer, ForeignKey('branches.id', ondelete='SET NULL'))  # override
    imported_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)

    segment = relationship('Segment', back_populates='assignments')
    branch = relationship('Branch', back_populates='assignments')


# ──────────────────────────────────────────────────────────────────────────────
# Sync infrastructure
# ──────────────────────────────────────────────────────────────────────────────

class SyncLog(Base):
    __tablename__ = 'sync_log'

    id = Column(Integer, primary_key=True)
    started_at = Column(TIMESTAMP(timezone=True))
    finished_at = Column(TIMESTAMP(timezone=True))
    total_received = Column(Integer, default=0)
    total_mapped = Column(Integer, default=0)
    total_unmapped = Column(Integer, default=0)

    collected_records = relationship('CollectedRecord', back_populates='sync_log')
    unmapped_records = relationship('UnmappedRecord', back_populates='sync_log')


class SyncCursor(Base):
    """Single-row table storing the incremental sync cursor."""
    __tablename__ = 'sync_cursor'

    id = Column(Integer, primary_key=True)
    last_synced_at = Column(TIMESTAMP(timezone=True))
    last_record_id = Column(Text)  # source record ID for same-timestamp tie-breaking
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# Collected records
# ──────────────────────────────────────────────────────────────────────────────

class CollectedRecord(Base):
    __tablename__ = 'collected_records'

    id = Column(Integer, primary_key=True)
    source_record_id = Column(Text, nullable=False, unique=True)
    segment_id = Column(Integer, ForeignKey('segments.id', ondelete='SET NULL'))  # null if unmapped
    vi_tri = Column(SmallInteger)
    raw_data = Column(JSONB)
    is_active = Column(Boolean, default=True, nullable=False)  # false if soft-deleted in source

    # first_seen_at: set on INSERT, never updated — used for velocity / branch alerts
    first_seen_at = Column(TIMESTAMP(timezone=True), nullable=False)
    # last_synced_at: updated on every re-sync (edits, re-fetch)
    last_synced_at = Column(TIMESTAMP(timezone=True))

    sync_log_id = Column(Integer, ForeignKey('sync_log.id', ondelete='SET NULL'))

    segment = relationship('Segment', back_populates='collected_records')
    sync_log = relationship('SyncLog', back_populates='collected_records')


class UnmappedRecord(Base):
    __tablename__ = 'unmapped_records'

    id = Column(Integer, primary_key=True)
    source_record_id = Column(Text)
    raw_data = Column(JSONB)
    reason = Column(Text)
    resolved = Column(Boolean, default=False, nullable=False)
    sync_log_id = Column(Integer, ForeignKey('sync_log.id', ondelete='SET NULL'))

    sync_log = relationship('SyncLog', back_populates='unmapped_records')


# ──────────────────────────────────────────────────────────────────────────────
# Verification
# ──────────────────────────────────────────────────────────────────────────────

class VerificationLog(Base):
    __tablename__ = 'verification_log'

    id = Column(Integer, primary_key=True)
    segment_id = Column(Integer, ForeignKey('segments.id', ondelete='CASCADE'), nullable=False)
    nguoi_kiem_tra = Column(Text)
    ket_qua = Column(Text)
    loai_kiem_tra = Column(VARCHAR(10), nullable=False, server_default='auto')
    source_record_ids = Column(JSONB)   # list[str] of source_record_id values — nullable
    verified_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)

    segment = relationship('Segment', back_populates='verification_logs')


# ──────────────────────────────────────────────────────────────────────────────
# Indexes
# ──────────────────────────────────────────────────────────────────────────────

Index('ix_segments_norm',
      Segment.tinh_thanh_norm, Segment.xa_phuong_norm,
      Segment.ten_duong_norm, Segment.doan_key_norm)
Index('ix_segments_nhom', Segment.nhom)
Index('ix_segments_active', Segment.is_active)
Index('ix_collected_segment_vitri', CollectedRecord.segment_id, CollectedRecord.vi_tri)
Index('ix_collected_source_id', CollectedRecord.source_record_id)
Index('ix_collected_first_seen', CollectedRecord.first_seen_at)
Index('ix_unmapped_resolved', UnmappedRecord.resolved)
Index('ix_branch_mappings_key', BranchMapping.key_type, BranchMapping.key_value)
