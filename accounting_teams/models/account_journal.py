# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    # اسم جدول العلاقة مطابق لما في account.team.journal_ids حتى يكونا
    # وجهين لعلاقة واحدة (تُضبط من الدفتر، وتُقرأ من الفريق).
    team_ids = fields.Many2many(
        'account.team', 'account_journal_team_rel', 'journal_id', 'team_id',
        string='الفرق المحاسبية المسموح لها',
        help='اتركه فارغاً ليبقى الدفتر مرئياً لكل المحاسبين (السلوك '
             'الافتراضي). متى ما حُدِّد فريق أو أكثر، ينحصر الدفتر - وكل '
             'قيوده وفواتيره وبنودها - على أعضاء تلك الفرق ومدير المحاسبة.',
    )
