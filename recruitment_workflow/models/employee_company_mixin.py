# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EmployeeCompanyMixin(models.AbstractModel):
    """شركة السجل تتبع الموظف، لا الشركة المفعَّلة في مبدِّل المستخدم.

    كانت كل سجلات الموظفين في هذا الموديول تأخذ
    ``default=lambda self: self.env.company`` - أي شركة المستخدم لحظة
    الإنشاء. فمن ينشئ طلباً لموظف في فرع آخر يُسجّله على فرعه هو، وعلى
    هذه النماذج قاعدة عزل ``company_id in company_ids``: فيختفي السجل
    عن فرع صاحبه ويظهر لفرع لا شأن له به، وتُحسب إحصاءات الفروع خطأً.

    نفس المبدأ المطبَّق في السداد البنكي
    (bank_settlement_mixin._fill_employee_derived_vals): الاشتقاق من
    جهة الخادم في create/write وليس في onchange وحده - النداءات عبر
    RPC/API لا تمر بـonchange إطلاقاً.
    """
    _name = 'recruitment.workflow.employee.company.mixin'
    _description = 'اشتقاق شركة السجل من الموظف'

    # مصادر الشركة مرتَّبة: أول مصدر له شركة يفوز. النماذج التي لا موظف
    # لها بالضرورة (بلاغ الحادث مثلاً) تضيف مصدراً بديلاً (المركبة).
    _COMPANY_SOURCES = ('employee_id',)

    def _company_from_sources(self, vals):
        """sudo(): شركة الموظف حقل "خاص" من منظور hr.employee.public،
        ومنشئ الطلب (مسؤول مشروع/عمليات) لا يملك hr.group_hr_user
        بالضرورة - نفس سبب sudo في _onchange_employee_id."""
        for fname in self._COMPANY_SOURCES:
            if fname not in self._fields:
                continue
            record_id = vals.get(fname)
            if not record_id:
                continue
            source = self.env[self._fields[fname].comodel_name].sudo().browse(record_id)
            if source.exists() and source.company_id:
                return source.company_id.id
        return False

    def _fill_company_from_employee(self, vals):
        company_id = self._company_from_sources(vals)
        if company_id:
            vals['company_id'] = company_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._fill_company_from_employee(vals)
        return super().create(vals_list)

    def write(self, vals):
        # تغيّر الموظف => تتبعه الشركة. لا نلمسها إن لم يتغيّر مصدرها،
        # كي يبقى التعديل اليدوي الاستثنائي ممكناً.
        if any(f in vals for f in self._COMPANY_SOURCES):
            self._fill_company_from_employee(vals)
        return super().write(vals)

    @api.onchange('employee_id')
    def _onchange_employee_company(self):
        """يُظهر الشركة الصحيحة في الشاشة فور اختيار الموظف - قبل الحفظ."""
        if 'employee_id' not in self._fields or not self.employee_id:
            return
        company = self.employee_id.sudo().company_id
        if company:
            self.company_id = company.id
