# -*- coding: utf-8 -*-
"""مسارات حساب المندوب - بيانات مالية على مسار عام.

كل مسار هنا يُرجع بيانات **صاحب رمز الجلسة وحده**، مشتقّةً من الرمز
لا من أي مُعرّف يرسله العميل. ولا يقبل مسار واحد مُعرّف موظف أو مندوب
في جسمه - وإلا كفى تغييرُ رقم في الطلب لقراءة كشف حساب غيره.
"""
import logging

from odoo import http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.quick_delivery.controllers.main import (
    BadRequest, _json_response, _session_driver, _throttle, api_endpoint,
    _body_json,
)

_logger = logging.getLogger(__name__)


class QuickDeliveryAccount(http.Controller):

    @http.route('/api/v1/driver/account', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_account(self, **kwargs):
        """كشف حساب المندوب - قراءة فقط.

        readonly=False رغم أنه لا يكتب: عدّاد حدّ المعدّل يكتب، ومؤشّر
        القراءة فقط يُسقطه.
        """
        driver = _session_driver()
        _throttle('driver', 'account-%s' % driver.id)
        return _json_response({
            'status': 'success',
            'account': driver._qd_account_summary(),
            'advance': driver._qd_advance_options(),
            'requests': driver._qd_advance_history(),
        })

    @http.route('/api/v1/driver/advance/request', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    @api_endpoint
    def driver_request_advance(self, **kwargs):
        driver = _session_driver()
        # حدّ ضيّق: طلب السلفة يُنشئ سجلاً مالياً، وحلقةٌ معطوبة تملأ
        # صندوق المحاسبة بمئات الطلبات.
        _throttle('login', 'advance-%s' % driver.id)
        data = _body_json()
        try:
            advance = driver._qd_request_advance(
                amount=data.get('amount'),
                reason_id=data.get('reason_id'),
                method=data.get('method'),
                detail=data.get('detail'),
                note=str(data.get('note') or '')[:500],
            )
        except (UserError, ValidationError) as error:
            # رسالة السداد البنكي تصل المندوب كما هي: "المبلغ يجب أن
            # يكون موجباً" أوضح من "خطأ في الطلب".
            raise BadRequest(
                error.args[0] if error.args else _('تعذّر رفع الطلب'), 400)
        return _json_response({
            'status': 'success',
            'name': advance.name,
            'state': advance.state,
            'message': _('رُفع طلبك %s وهو الآن بانتظار الموافقة.')
                       % advance.name,
            'requests': driver._qd_advance_history(),
        })
