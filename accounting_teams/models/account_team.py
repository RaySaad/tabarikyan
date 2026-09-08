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

    def _register_hook(self):
        """يُعيد تطبيق تعديل قواعد الرؤية بعد *كل* تحميل كامل للنظام.

        ليست احتياطاً بل ضرورة أثبتها الاختبار: قاعدة السداد البنكي
        معرَّفة في XML موديولها بكتلة noupdate="0"، فكل تحديث لذلك
        الموديول يُعيد كتابتها من ملفه ويمحو شرط الفريق - أي أن أي دفعة
        كود جديدة للسداد البنكي كانت ستفتح الثغرة من جديد بصمت. وينطبق
        الأمر على أي موديول آخر يُعيد كتابة قاعدة نعدّلها.

        _register_hook تُستدعى في الخطوة الأخيرة من تحميل الموديولات
        (بعد تحميلها كلها)، فأي قاعدة أعادها موديول لأصلها تُصحَّح فوراً
        في نفس العملية. والدالة لا تكتب شيئاً إن كانت القواعد مضبوطة،
        فتكلفتها قراءة بضعة سجلات لا أكثر."""
        super()._register_hook()
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

    # ------------------------------------------------------------------
    # أودو تُخزّن مجال قاعدة السجلات مؤقتاً لكل مستخدم بعد تعويض
    # user.accounting_team_ids فيه. فتغيير عضوية الفرق لا يُلتقَط تلقائياً
    # (أودو تُفرّغ هذه الذاكرة عند تعديل القواعد أو المجموعات فقط) - أي
    # أن إضافة موظف لفريق كانت *بلا أي أثر* حتى إعادة تشغيل الخادم، وهو
    # خلل مربك جداً: المدير يضيف العضو ويرى أن شيئاً لم يتغيّر.
    # ------------------------------------------------------------------
    def _clear_rule_cache(self):
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        teams = super().create(vals_list)
        teams._clear_rule_cache()
        return teams

    def write(self, vals):
        res = super().write(vals)
        self._clear_rule_cache()
        return res

    def unlink(self):
        self._clear_rule_cache()
        return super().unlink()

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
