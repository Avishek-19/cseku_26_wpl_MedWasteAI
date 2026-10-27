"""SQLite-only domain smoke tests; no PostgreSQL fixture or real payments."""
import unittest
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app import models  # noqa
from app.core.db import Base
from app.models.user import User
from app.models.roles import UserRole
from app.models.business import Organization, OrganizationPermit, Subscription, OperatorJobEvent, JournalLine, Journal
from app.services.business_finance import (bill_due, recycling_split, cycle_for, journal,
    operator_accepts_new_work, money)
from app.services.payment_gateway import MockGateway, SSLCommerzGateway, GatewayFailure


class FinanceDomainTests(unittest.TestCase):
    def test_bill_and_distribution(self):
        self.assertEqual(bill_due(7000, 900), Decimal('6100.00'))
        self.assertEqual(recycling_split(2000, 500), (
            Decimal('1500.00'), Decimal('900.00'),Decimal('450.00'), Decimal('150.00')))
        self.assertEqual(bill_due(500, 1000), Decimal('0.00'))
        self.assertEqual(sum(recycling_split('0.05', 0)[1:]), Decimal('0.05'))
        self.assertEqual(recycling_split(100, 125), (Decimal('0.00'),)*4)
        with self.assertRaises(ValueError): recycling_split(-1, 2)

    def test_15_day_dhaka_cycle_edges(self):
        anchor=date(2026,10,1)
        # Dhaka 1 Oct midnight corresponds to previous day 18:00 UTC.
        n,a,b=cycle_for(anchor,datetime(2026,9,30,18,tzinfo=timezone.utc))
        self.assertEqual(n,0)
        self.assertEqual(a,datetime(2026,9,30,18,tzinfo=timezone.utc))
        self.assertEqual(b,datetime(2026,10,15,18,tzinfo=timezone.utc))
        n,_,_=cycle_for(anchor,datetime(2026,10,15,18,tzinfo=timezone.utc))
        self.assertEqual(n,1)
        with self.assertRaises(ValueError): cycle_for(anchor,datetime(2026,10,2))
        with self.assertRaises(ValueError): cycle_for(anchor,datetime(2026,9,1,tzinfo=timezone.utc))

    def test_mock_never_validates_real_money(self):
        mock=MockGateway()
        session=mock.initiate(reference='t1',amount=Decimal(50),correlation='c',customer={},callbacks={})
        self.assertTrue(session.redirect_url.startswith('/dashboard/'))
        with self.assertRaises(GatewayFailure): mock.verify(provider_validation_id='anything')
        with self.assertRaises(GatewayFailure): SSLCommerzGateway(mode='live',store_id='',store_password='')

    def test_schema_and_operator_subscription_policy(self):
        engine=create_engine('sqlite+pysqlite:///:memory:',future=True)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user=User(email='operator@example.test',full_name='Operator Test',hashed_password='not-a-password',role=UserRole.COLLECTOR)
            db.add(user);db.flush()
            org=Organization(name='Test Collection Company',org_type='COLLECTION_COMPANY',status='pending',owner_user_id=user.id)
            db.add(org);db.flush()
            self.assertFalse(operator_accepts_new_work(db,org.id,date(2026,10,9)))
            org.status='verified'; db.flush()
            # Verification without an approved, current permit is not dispatch eligibility.
            self.assertFalse(operator_accepts_new_work(db,org.id,date(2026,10,9)))
            permit=OrganizationPermit(organization_id=org.id,permit_type='Waste transport',reference='PERMIT-2026-1',approval_status='approved',expires_on=date(2026,12,31))
            db.add(permit); db.flush()
            self.assertTrue(operator_accepts_new_work(db,org.id,date(2026,10,9)))
            for index in range(5):
                db.add(OperatorJobEvent(organization_id=org.id,job_reference=f'verified-job-{index}'))
            db.flush()
            self.assertFalse(operator_accepts_new_work(db,org.id,date(2026,10,9)))
            sub=Subscription(organization_id=org.id,period_start=date(2026,10,1),period_end=date(2026,11,1),price_bdt=Decimal('100'),state='unpaid')
            db.add(sub);db.flush()
            self.assertFalse(operator_accepts_new_work(db,org.id,date(2026,10,9)))
            sub.state='paid';db.flush()
            self.assertTrue(operator_accepts_new_work(db,org.id,date(2026,10,9)))
            self.assertFalse(operator_accepts_new_work(db,org.id,date(2026,11,1)))
            ev=db.scalar(select(OperatorJobEvent).where(OperatorJobEvent.job_reference=='verified-job-0'))
            ev.reversed_at=datetime.now(timezone.utc);db.flush()
            self.assertTrue(operator_accepts_new_work(db,org.id,date(2026,11,1)))
            permit.expires_on=date(2026,10,1);db.flush()
            self.assertFalse(operator_accepts_new_work(db,org.id,date(2026,11,1)))
            db.rollback()

    def test_balanced_journal_dedup_and_invalid(self):
        engine=create_engine('sqlite+pysqlite:///:memory:',future=True)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            with self.assertRaises(ValueError):
                journal(db,unique_event='invalid',description='imbalance',entries=[
                    ('cash','debit',Decimal(1),None),('revenue','credit',Decimal(2),None)])
            j=journal(db,unique_event='check-1',description='balanced',entries=[
                ('cash','debit',Decimal('42.00'),None),('revenue','credit',Decimal('42.00'),None)])
            same=journal(db,unique_event='check-1',description='duplicate',entries=[
                ('cash','debit',Decimal('42.00'),None),('revenue','credit',Decimal('42.00'),None)])
            self.assertEqual(j.id,same.id)
            self.assertEqual(db.scalar(select(func.count(Journal.id))),1)
            entries=list(db.scalars(select(JournalLine).where(JournalLine.journal_id==j.id)))
            self.assertEqual(sum((e.amount_bdt for e in entries if e.side=='debit'),Decimal(0)),
                             sum((e.amount_bdt for e in entries if e.side=='credit'),Decimal(0)))
            db.rollback()

if __name__=='__main__': unittest.main(verbosity=2)
