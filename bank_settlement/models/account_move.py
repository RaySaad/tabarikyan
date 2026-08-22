# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_bank_settlement_move = fields.Boolean(
        string='قيد سداد بنكي', default=False, copy=False,
        help='يُضبط تلقائياً عند إنشاء القيد من السداد البنكي - يُستخدم '
             'لحصر رؤية "مستخدم/محاسب" السداد البنكي على قيودهم المرتبطة '
             'فقط (انظر ir.rule في security.xml)، دون الحاجة لصلاحية '
             'محاسبية واسعة تكشف بقية قيود الشركة.',
    )

    # ثغرة حقيقية اكتُشفت من الاستخدام الفعلي: أي مستخدم يملك صلاحية حذف
    # في المحاسبة يقدر يرجّع قيد السداد البنكي لمسودة (button_draft) ثم
    # يحذفه نهائياً - رغم أن سجل السداد نفسه (سلفة/رسوم حكومية/...) يبقى
    # ظاهراً بحالة "تم الصرف/منفّذ" وكأن كل شيء سليم، بينما القيد المحاسبي
    # الذي يوثّقه اختفى فعلياً من الدفاتر. هذا أنتج فعلياً تناقضاً حقيقياً
    # في كشف حساب موظف حقيقي (قيد سلفة بحساب 212003 اختفى، وحل محله قيد
    # يدوي منفصل باتجاه معكوس). القيد المُنشأ من السداد البنكي يجب أن يبقى
    # ثابتاً ومعتمداً دائماً للتدقيق - نفس فلسفة hr_employee.unlink()
    # (امنع الحذف/التعديل الجوهري، اطلب استخدام قيد عكسي/إلغاء إن احتاج
    # الأمر تصحيحاً بدل حذف السجل الأصلي أو تغيير حالته).
    def unlink(self):
        # bank_settlement_admin_force_delete: استثناء إداري صريح ومُسجَّل
        # (سجل bank.settlement.deletion.log) لـ"الحذف النهائي الإداري" -
        # انظر bank_settlement_mixin.action_admin_force_delete. يُستخدم
        # فقط لقيد لا يزال مسودة (لم يُرحَّل بعد)؛ قيد مرحّل يُعكَس هناك
        # بدل حذفه، فلا يمر من هنا أصلاً.
        if not self.env.context.get('bank_settlement_admin_force_delete'):
            for move in self:
                if move.is_bank_settlement_move:
                    raise UserError(_(
                        'لا يمكن حذف القيد المحاسبي "%s" نهائياً - هو قيد سداد '
                        'بنكي مرتبط بسجل معتمد (سلفة، رسوم حكومية، تأمين طبي، '
                        'تحويل مركبة، أو تصفية) يجب الحفاظ عليه للتدقيق. إن '
                        'احتاج الأمر تصحيحاً، استخدم قيداً عكسياً أو الإلغاء '
                        'بدلاً من الحذف.'
                    ) % move.name)
        return super().unlink()

    def button_draft(self):
        for move in self:
            if move.is_bank_settlement_move:
                raise UserError(_(
                    'لا يمكن إرجاع القيد المحاسبي "%s" لمسودة - هو قيد '
                    'سداد بنكي مرتبط بسجل معتمد، يجب الحفاظ عليه معتمداً '
                    'للتدقيق. استخدم قيداً عكسياً أو الإلغاء بدلاً من ذلك.'
                ) % move.name)
        return super().button_draft()
