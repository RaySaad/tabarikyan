# -*- coding: utf-8 -*-
from odoo import models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _bank_settlement_outstanding_account(self, inbound=False, company=None):
        """حساب المدفوعات/المقبوضات المعلقة لهذا الدفتر - أو False.

        بنفس ترتيب أودو في مدفوعاتها (account.payment._get_outstanding_
        account) حتى تُطابِق أداةُ المطابقة البنكية قيودَ السداد البنكي
        كما تُطابق مدفوعات أودو تماماً.

        هنا لا في الـ mixin: يستعمله صرفُ السداد (بدفتر السجل) واسترداد
        السلفة (بدفتر الاسترداد، وقد يكون غير دفتر الصرف) - والفرق بينهما
        هو الدفتر وحده."""
        # يقبل سجلاً فارغاً عمداً: سجل سداد بلا دفتر يومية محدَّد بعد
        # (الدفتر يُدخَل وقت الصرف) يصل إلى هنا، وensure_one() كانت
        # تُفجّره بدل الرجوع لحساب الشركة - انحدار كشفته الاختبارات.
        if len(self) > 1:
            raise ValueError(
                'حساب المدفوعات المعلقة يُحسب لدفتر يومية واحد: %s' % self)
        method_lines = (
            self.inbound_payment_method_line_ids if inbound
            else self.outbound_payment_method_line_ids
        )
        for line in method_lines:
            if line.payment_account_id:
                return line.payment_account_id
        company = company or self.company_id or self.env.company
        chart = self.env['account.chart.template'].with_context(
            allowed_company_ids=company.root_id.ids)
        account = chart.ref(
            'account_journal_payment_debit_account_id' if inbound
            else 'account_journal_payment_credit_account_id',
            raise_if_not_found=False)
        return account or company.transfer_account_id
