"""Recover delayed/lost gateway callbacks through authenticated provider queries."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_, select
from app.core.config import get_settings
from app.models.business import PaymentIntent
from app.services.payment_gateway import SSLCommerzGateway, GatewayFailure, VerifiedPayment
from app.services.payment_settlement import _settle_verified


def gateway_for_settings(cfg):
    return SSLCommerzGateway(mode=cfg.payment_mode, store_id=cfg.sslcz_store_id,
                            store_password=cfg.sslcz_store_password)


def reconcile_payment_batch(db, limit=5):
    cfg = get_settings()
    result = {'checked': 0, 'settled': 0, 'unavailable': 0}
    if cfg.payment_mode not in {'sandbox', 'live'}:
        return result
    now = datetime.now(timezone.utc)
    ids = list(db.scalars(select(PaymentIntent.id).where(
        PaymentIntent.mode == cfg.payment_mode, PaymentIntent.state.in_(['created', 'pending']),
        PaymentIntent.created_at < now - timedelta(seconds=30),
        or_(PaymentIntent.last_checked_at.is_(None), PaymentIntent.last_checked_at < now - timedelta(minutes=2)),
    ).order_by(PaymentIntent.created_at).limit(limit)).all())
    db.commit()
    for identifier in ids:
        try:
            row = db.scalar(select(PaymentIntent).where(PaymentIntent.id == identifier)
                .with_for_update(skip_locked=True, of=PaymentIntent).execution_options(populate_existing=True))
            if not row or row.state not in {'created', 'pending'}:
                db.rollback(); continue
            checked = row.last_checked_at
            if checked is not None:
                checked = checked.replace(tzinfo=timezone.utc) if checked.tzinfo is None else checked
                if checked > now - timedelta(minutes=2):
                    db.rollback(); continue
            row.last_checked_at = now
            row.reconciliation_attempts += 1
            receipt = gateway_for_settings(cfg).query(reference=row.merchant_reference)
            if isinstance(receipt, VerifiedPayment):
                _settle_verified(db, row, receipt)
                result['settled'] += int(row.state == 'succeeded')
            elif receipt in {'failed', 'cancelled', 'expired'}:
                row.state = receipt
            db.commit(); result['checked'] += 1
        except Exception:
            db.rollback()
            # Persist retry backoff even when the provider is unavailable.
            row = db.scalar(select(PaymentIntent).where(PaymentIntent.id == identifier)
                .with_for_update(of=PaymentIntent))
            if row:
                row.last_checked_at = now
                row.reconciliation_attempts += 1
                db.commit()
            result['unavailable'] += 1
    return result
