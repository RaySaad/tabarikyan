# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AccountTeam(models.Model):
    """فريق محاسبي - وحدة تقسيم الصلاحيات داخل قسم المحاسبة.

    أودو قياسياً لا تفرّق بين المحاسبين: من يملك صلاحية المحاسبة يرى كل
    الدفاتر وكل القيود والفواتير. هذا النموذج يضيف طبقة "فريق" تُربَط
    بدفاتر اليومية، فيرى كل محاسب دفاتر فريقه وقيودها فقط (محاسب
    الموردين لا يرى فواتير العملاء، والعكس).

    مبدأ أساسي: التقييد يسري على المحاسبين العاديين فقط - "مدير
    المحاسبة" (Administrator) معفى تماماً ويرى كل شيء. التنفيذ يعتمد على
    أن قواعد السجلات المرتبطة بمجموعات تُدمَج بـOR: قاعدة مقيِّدة على
    مجموعة المحاسبين + قاعدة مفتوحة على مجموعة المدير = المدير يرى الكل
    لأنه عضو في المجموعتين (انظر security/account_team_security.xml).
    """
    _name = 'account.team'
    _description = 'الفريق المحاسبي'
    _order = 'name'

    def init(self):
        """يُعيد تطبيق تعديل قواعد أودو المفتوحة في *كل* تحديث للموديول،
        لا عند التثبيت وحده.

        ضروري وليس احتياطاً: post_init_hook لا يعمل إلا مرة واحدة عند
        التثبيت. وأي شيء يُعيد تلك القواعد لأصلها لاحقاً (تحديث نسخة
        أودو نفسها، أو تعديل يدوي من الإعدادات التقنية، أو إلغاء تثبيت
        الموديول ثم إعادة تثبيته بترتيب مختلف) كان سيترك الموديول
        "مثبَّتاً" وشاشاته ظاهرة بينما التقييد لا يعمل إطلاقاً - أخطر
        أنواع الأعطال: صلاحية يظنها المستخدم مفعّلة وهي ليست كذلك.

        init() يستدعيها أودو بعد تجهيز جداول النموذج في كل تثبيت
        وتحديث، والدالة نفسها idempotent (تكتب نفس القيمة)."""
        from odoo.addons.accounting_teams import _apply_team_rules
        _apply_team_rules(self.env)

    name = fields.Char(string='الفريق المحاسبي', required=True, translate=True)
    user_id = fields.Many2one(
        'res.users', string='قائد الفريق', ondelete='restrict',
        default=lambda self: self.env.user,
        help='مسؤول الفريق - للمرجعية الإدارية؛ لا يمنحه وحده أي صلاحية '
             'إضافية ما لم يكن ضمن الأعضاء أيضاً.',
    )
    company_id = fields.Many2one(
        'res.company', string='الشركة', required=True,
        default=lambda self: self.env.company, ondelete='restrict',
        help='الفرع/الشركة التي يعمل عليها هذا الفريق - يمكن إنشاء فرق '
             'مستقلة لكل فرع عند استخدام تعدد الشركات.',
    )
    # علاقة حقيقية (وليست محسوبة) حتى يتوفر عكسها على المستخدم مباشرة
    # ويصلح للاستخدام داخل قواعد السجلات بلا أي حساب إضافي.
    member_ids = fields.Many2many(
        'res.users', 'account_team_users_rel', 'team_id', 'user_id',
        string='أعضاء الفريق',
        help='المستخدمون الذين يرون دفاتر هذا الفريق وقيودها.',
    )
    journal_ids = fields.Many2many(
        'account.journal', 'account_journal_team_rel', 'team_id', 'journal_id',
        string='الدفاتر المسموح بها', readonly=True,
        help='تُضبط من شاشة دفتر اليومية نفسه (حقل "الفرق المحاسبية المسموح لها").',
    )
    active = fields.Boolean(default=True)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        'يوجد فريق محاسبي آخر بنفس الاسم في نفس الشركة بالفعل.',
    )

    @api.constrains('member_ids', 'company_id')
    def _check_members_company(self):
        """عضو لا ينتمي لشركة الفريق لن يرى دفاتره أصلاً (قاعدة عزل
        الشركات القياسية بأودو تمنعه) - فإضافته وهمٌ يوهم بصلاحية غير
        فعّالة."""
        for team in self:
            outsiders = team.member_ids.filtered(
                lambda u: team.company_id not in u.company_ids
            )
            if outsiders:
                raise ValidationError(_(
                    'المستخدمون التالون لا ينتمون لشركة الفريق "%(company)s" '
                    'فلن يروا دفاتره فعلياً: %(users)s'
                ) % {
                    'company': team.company_id.display_name,
                    'users': ', '.join(outsiders.mapped('name')),
                })
