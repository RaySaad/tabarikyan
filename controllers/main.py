# -*- coding: utf-8 -*-
import re

from psycopg2 import IntegrityError

from odoo import http, _
from odoo.http import request

MOBILE_PATTERN = re.compile(r'^(?:(?:\+?966)|0)5\d{8}$')


class RecruitmentWebsiteController(http.Controller):

    def _clean_mobile(self, value):
        return (value or '').strip().replace(' ', '').replace('-', '')

    def _to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _validate(self, values):
        """يعيد قاموس أخطاء لكل حقل غير صالح - نفس قواعد التحقق المطبَّقة
        على recruitment.request (models/recruitment_request.py) لكن قبل
        الوصول لقاعدة البيانات، حتى لا يظهر خطأ تقني للزائر العام."""
        errors = {}

        name = (values.get('employee_name') or '').strip()
        if not name:
            errors['employee_name'] = _('الرجاء إدخال الاسم الكامل.')

        identification_id = (values.get('identification_id') or '').strip()
        if not identification_id:
            errors['identification_id'] = _('الرجاء إدخال رقم الهوية/الإقامة.')
        elif not identification_id.isdigit():
            errors['identification_id'] = _('رقم الهوية يجب أن يحتوي على أرقام فقط.')
        elif len(identification_id) != 10:
            errors['identification_id'] = _('رقم الهوية يجب أن يتكون من 10 أرقام بالضبط.')
        elif identification_id[0] not in ('1', '2'):
            errors['identification_id'] = _('رقم الهوية يجب أن يبدأ بالرقم 1 أو 2.')

        mobile = self._clean_mobile(values.get('mobile'))
        if not mobile:
            errors['mobile'] = _('الرجاء إدخال رقم الجوال.')
        elif not MOBILE_PATTERN.match(mobile):
            errors['mobile'] = _('رقم الجوال غير صالح. مثال: 05XXXXXXXX.')

        email = (values.get('email') or '').strip()
        if not email or '@' not in email:
            errors['email'] = _('الرجاء إدخال بريد إلكتروني صالح.')

        gender = values.get('gender')
        valid_genders = dict(request.env['recruitment.request']._fields['gender'].selection)
        if not gender or gender not in valid_genders:
            errors['gender'] = _('الرجاء اختيار الجنس.')

        country_id = self._to_int(values.get('country_id'))
        if not country_id or not request.env['res.country'].sudo().browse(country_id).exists():
            errors['country_id'] = _('الرجاء اختيار الجنسية.')

        project_id = self._to_int(values.get('project_id'))
        if not project_id or not request.env['project.project'].sudo().browse(project_id).exists():
            errors['project_id'] = _('الرجاء اختيار المشروع/المنصة.')

        if identification_id and identification_id.isdigit() and len(identification_id) == 10 \
                and 'identification_id' not in errors:
            existing = request.env['recruitment.request'].sudo().search_count([
                ('identification_id', '=', identification_id),
            ])
            if existing:
                errors['identification_id'] = _(
                    'يوجد تسجيل سابق بنفس رقم الهوية/الإقامة. إن كنت قدّمت من قبل، '
                    'سيتواصل معك فريقنا قريباً.'
                )

        return errors

    def _form_context(self, error=None, default=None):
        return {
            'error': error or {},
            'default': default or {},
            'genders': request.env['recruitment.request']._fields['gender'].selection,
            'countries': request.env['res.country'].sudo().search([], order='name'),
            'projects': request.env['project.project'].sudo().search(
                [('active', '=', True)], order='name',
            ),
        }

    @http.route('/careers/register', type='http', auth='public', website=True, sitemap=True)
    def careers_register(self, **kwargs):
        error = {}
        default = {}
        if 'recruitment_workflow_error' in request.session:
            error = request.session.pop('recruitment_workflow_error')
            default = request.session.pop('recruitment_workflow_default')
        return request.render(
            'recruitment_workflow.website_careers_register',
            self._form_context(error=error, default=default),
        )

    @http.route('/careers/register/submit', type='http', auth='public', website=True, methods=['POST'],
                sitemap=False, csrf=True)
    def careers_register_submit(self, **post):
        errors = self._validate(post)
        if errors:
            request.session['recruitment_workflow_error'] = errors
            request.session['recruitment_workflow_default'] = post
            return request.redirect('/careers/register')

        try:
            with request.env.cr.savepoint():
                request.env['recruitment.request'].sudo().create({
                    'employee_name': (post.get('employee_name') or '').strip(),
                    'identification_id': (post.get('identification_id') or '').strip(),
                    'mobile': self._clean_mobile(post.get('mobile')),
                    'email': (post.get('email') or '').strip(),
                    'gender': post.get('gender'),
                    'country_id': self._to_int(post.get('country_id')),
                    'project_id': self._to_int(post.get('project_id')),
                })
        except IntegrityError:
            # حالة نادرة: تسجيلان بنفس رقم الهوية في نفس اللحظة تقريباً.
            request.session['recruitment_workflow_error'] = {
                'identification_id': _(
                    'يوجد تسجيل سابق بنفس رقم الهوية/الإقامة. إن كنت قدّمت من قبل، '
                    'سيتواصل معك فريقنا قريباً.'
                ),
            }
            request.session['recruitment_workflow_default'] = post
            return request.redirect('/careers/register')
        return request.redirect('/careers/register/thank-you')

    @http.route('/careers/register/thank-you', type='http', auth='public', website=True, sitemap=False)
    def careers_register_thanks(self, **kwargs):
        return request.render('recruitment_workflow.website_careers_thank_you', {})
