# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestRecruitmentStage(TransactionCase):

    def test_code_required(self):
        """رمز المرحلة إجباري - يمنع إنشاء مرحلة بلا رمز فني، لأن معظم منطق
        سير العمل (recruitment_request.py) يعتمد على code كمفتاح منطقي."""
        with self.assertRaises(Exception):
            self.env['recruitment.stage'].create({'name': 'مرحلة بدون رمز'})

    def test_code_uniqueness(self):
        """رمز المرحلة يجب أن يكون فريداً، وإلا ينكسر _get_stage_by_code
        و _STAGE_APPROVAL_GROUP و _STAGE_RESPONSIBLE_GROUP بصمت."""
        self.env['recruitment.stage'].create({
            'name': 'مرحلة تجريبية 1', 'code': 'test_dup_code', 'sequence': 500,
        })
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['recruitment.stage'].create({
                'name': 'مرحلة تجريبية 2', 'code': 'test_dup_code', 'sequence': 510,
            })
