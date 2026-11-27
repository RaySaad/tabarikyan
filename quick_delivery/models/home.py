# -*- coding: utf-8 -*-
"""الصفحة الرئيسية للتوصيل الفوري: السوبرماركتات أيقوناتٍ.

نفس هوية مركز السداد البنكي في هذا المستودع: ترويسة داكنة ومربّعات
كبيرة تُفتح بضغطة. الفرق أن المربّعات هنا **ليست ثابتة**: كل سوبرماركت
مربّعه، فإضافة بندة أو غيرها تُضيف أيقونتها وحدها.

البطاقات تُحسب في الخادم بصلاحية المستخدم - لا تُبنى في الواجهة ثم
تُخفى.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError

DISPATCHER_GROUP = 'quick_delivery.group_qd_dispatcher'

# ألوان المربّعات بالدور: لا معنى دلالياً لها، غرضها التمييز البصري
# بين الشركات.
TONES = ('blue', 'green', 'violet', 'amber', 'cyan', 'red')


class QuickDeliveryHome(models.AbstractModel):
    _name = 'quick.delivery.home'
    _description = 'الصفحة الرئيسية للتوصيل الفوري'

    @api.model
    def get_home(self):
        if not self.env.user.has_group(DISPATCHER_GROUP):
            raise AccessError(_('التوصيل الفوري محصور بفريق التوصيل.'))

        Order = self.env['quick.delivery.order'].sudo()
        Driver = self.env['quick.delivery.driver'].sudo()
        Inbox = self.env['quick.delivery.inbox'].sudo()
        Partner = self.env['res.partner'].sudo()

        now = fields.Datetime.now()
        day_start = Order._day_start_utc_for_env()
        open_states = list(Order.OPEN_STATES)

        clients = Partner.search([('is_qcommerce_client', '=', True)],
                                 order='name')

        def grouped(domain):
            return {client.id: count for client, count in Order._read_group(
                domain + [('client_id', 'in', clients.ids)],
                groupby=['client_id'], aggregates=['__count'])}

        active = grouped([('state', 'in', open_states)])
        late = grouped([('state', 'in', open_states),
                        ('sla_deadline', '<', now)])
        today = grouped([('state', '=', 'delivered'),
                         ('delivered_at', '>=', day_start)])
        pending_inbox = {client.id: count for client, count
                         in Inbox._read_group(
                             [('client_id', 'in', clients.ids),
                              ('state', 'not in', ['mapped', 'ignored'])],
                             groupby=['client_id'], aggregates=['__count'])}

        merchants = []
        for index, client in enumerate(clients):
            merchants.append({
                'id': client.id,
                'name': client.name,
                'tone': TONES[index % len(TONES)],
                # شعار الشركة إن رُفع، وإلا أيقونة: الشعار يُميّز
                # العثيم من بندة أسرع من قراءة الاسم.
                'has_logo': bool(client.image_128),
                'active_count': active.get(client.id, 0),
                'late_count': late.get(client.id, 0),
                'today_count': today.get(client.id, 0),
                'configured': bool(client.api_key and client.webhook_url),
                'capture_mode': client.qd_capture_mode,
                'inbox_pending': pending_inbox.get(client.id, 0),
            })

        drivers = Driver.search([])
        all_active = Order.search_count([('state', 'in', open_states)])
        all_late = Order.search_count([('state', 'in', open_states),
                                       ('sla_deadline', '<', now)])
        delivered_today = Order.search([('state', '=', 'delivered'),
                                        ('delivered_at', '>=', day_start)])
        cod_today = sum(delivered_today.filtered(
            lambda rec: rec.payment_method == 'COD').mapped('cod_amount'))

        is_manager = self.env.user.has_group(
            'quick_delivery.group_qd_manager')
        extras = [
            {'key': 'dashboard', 'name': 'غرفة العمليات والخريطة',
             'icon': 'fa-map-marker', 'tone': 'blue',
             'action': 'quick_delivery.action_quick_sla_dashboard'},
            {'key': 'orders', 'name': 'كل الطلبات',
             'icon': 'fa-list', 'tone': 'cyan',
             'action': 'quick_delivery.action_quick_delivery_orders'},
            {'key': 'drivers', 'name': 'المندوبون',
             'icon': 'fa-motorcycle', 'tone': 'green',
             'action': 'quick_delivery.action_quick_delivery_drivers'},
            {'key': 'clients', 'name': 'إدارة السوبرماركتات',
             'icon': 'fa-building', 'tone': 'violet',
             'action': 'quick_delivery.action_qcommerce_clients'},
            {'key': 'inbox', 'name': 'الوارد من التجّار',
             'icon': 'fa-inbox', 'tone': 'amber',
             'action': 'quick_delivery.action_quick_delivery_inbox'},
        ]
        if is_manager:
            extras.append(
                {'key': 'webhooks', 'name': 'إبلاغات التاجر',
                 'icon': 'fa-paper-plane', 'tone': 'red',
                 'action': 'quick_delivery.action_quick_delivery_webhooks'})

        return {
            'user_name': self.env.user.name,
            'currency': {
                'symbol': self.env.company.currency_id.symbol or 'ر.س'},
            'kpis': {
                'active': all_active,
                'late': all_late,
                'unassigned': Order.search_count(
                    [('state', '=', 'searching_driver')]),
                'online_drivers': len(drivers.filtered(
                    lambda drv: drv.driver_status == 'online')),
                'busy_drivers': len(drivers.filtered(
                    lambda drv: drv.driver_status == 'busy')),
                'delivered_today': len(delivered_today),
                'cod_today': cod_today,
            },
            'merchants': merchants,
            'extras': extras,
        }
