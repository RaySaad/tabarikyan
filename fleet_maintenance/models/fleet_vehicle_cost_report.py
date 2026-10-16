# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools


class FleetVehicleCostReport(models.Model):
    """تقرير تكلفة المركبة: الأجرة المحصَّلة مقابل ما أنفِق عليها.

    هذا هو الرقم الذي تُضبَط به التعرفة: مركبة أجرتها 3000 وتكلفتها
    4200 تخسر 1200 شهرياً، ولا يظهر ذلك في أي شاشة أخرى - الأجرة في
    مستند التحميل، والصيانة في سجلات الخدمة، والحوادث في البلاغات.

    عرض SQL للقراءة فقط (_auto = False): تجميع لا يُخزَّن ولا يحتاج
    مزامنة، ويقبل التجميع المحوري (pivot) والفلترة كأي نموذج.
    """
    _name = 'fleet.vehicle.cost.report'
    _description = 'تقرير تكلفة المركبة'
    _auto = False
    _order = 'period desc, vehicle_id'

    period = fields.Date(string='الشهر', readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='المركبة', readonly=True)
    company_id = fields.Many2one('res.company', string='الشركة', readonly=True)
    rent_amount = fields.Float(string='الأجرة المحصَّلة', readonly=True)
    service_amount = fields.Float(string='الصيانة والأعطال', readonly=True)
    fuel_amount = fields.Float(string='الوقود (على الفرع)', readonly=True)
    fuel_liters = fields.Float(string='اللترات', readonly=True)
    damage_amount = fields.Float(string='الحوادث والتلفيات', readonly=True)
    total_cost = fields.Float(string='تكلفة الأسطول', readonly=True)
    net_result = fields.Float(string='صافي الأسطول', readonly=True)
    branch_cost = fields.Float(string='تكلفة الفرع', readonly=True)

    @property
    def _table_query(self):
        return """
            WITH rent AS (
                SELECT date_trunc('month', c.period_date)::date AS period,
                       l.vehicle_id,
                       c.company_id,
                       SUM(l.amount) AS rent_amount
                  FROM fleet_branch_rental_charge_line l
                  JOIN fleet_branch_rental_charge c ON c.id = l.charge_id
                 WHERE l.line_type = 'rent' AND c.state != 'cancel'
                 GROUP BY 1, 2, 3
            ), damage AS (
                SELECT date_trunc('month', c.period_date)::date AS period,
                       l.vehicle_id,
                       c.company_id,
                       SUM(l.amount) AS damage_amount
                  FROM fleet_branch_rental_charge_line l
                  JOIN fleet_branch_rental_charge c ON c.id = l.charge_id
                 WHERE l.line_type = 'damage' AND c.state != 'cancel'
                 GROUP BY 1, 2, 3
            ), service AS (
                SELECT date_trunc('month', s.date)::date AS period,
                       s.vehicle_id,
                       v.company_id,
                       SUM(s.amount) AS service_amount
                  FROM fleet_vehicle_log_services s
                  JOIN fleet_vehicle v ON v.id = s.vehicle_id
                 WHERE s.date IS NOT NULL
                 GROUP BY 1, 2, 3
            ), fuel AS (
                -- الوقود يدفعه المستأجر: يُنسب للفرع المتحمِّل ولا يدخل
                -- تكلفة الأسطول ولا صافيه.
                SELECT date_trunc('month', f.date)::date AS period,
                       f.vehicle_id,
                       f.company_id,
                       SUM(f.amount) AS fuel_amount,
                       SUM(f.liters) AS fuel_liters
                  FROM fleet_fuel_log f
                 GROUP BY 1, 2, 3
            ), keys AS (
                SELECT period, vehicle_id, company_id FROM rent
                UNION
                SELECT period, vehicle_id, company_id FROM damage
                UNION
                SELECT period, vehicle_id, company_id FROM service
                UNION
                SELECT period, vehicle_id, company_id FROM fuel
            )
            SELECT row_number() OVER () AS id,
                   k.period,
                   k.vehicle_id,
                   k.company_id,
                   COALESCE(r.rent_amount, 0.0) AS rent_amount,
                   COALESCE(s.service_amount, 0.0) AS service_amount,
                   COALESCE(d.damage_amount, 0.0) AS damage_amount,
                   COALESCE(fu.fuel_amount, 0.0) AS fuel_amount,
                   COALESCE(fu.fuel_liters, 0.0) AS fuel_liters,
                   COALESCE(s.service_amount, 0.0) AS total_cost,
                   -- ما يتحمله الفرع: أجرة + تلفيات محمَّلة + وقوده.
                   COALESCE(r.rent_amount, 0.0) + COALESCE(d.damage_amount, 0.0)
                       + COALESCE(fu.fuel_amount, 0.0) AS branch_cost,
                   -- صافي الأسطول: ما حصّله (أجرة + ما حمّله من تلفيات)
                   -- ناقص ما أنفقه على الورشة. فالتلفيات تُسترد من الفرع
                   -- بينما تكلفتها ضمن سجلات الخدمة نفسها.
                   COALESCE(r.rent_amount, 0.0) + COALESCE(d.damage_amount, 0.0)
                       - COALESCE(s.service_amount, 0.0) AS net_result
              FROM keys k
              LEFT JOIN rent r ON r.period = k.period
                               AND r.vehicle_id IS NOT DISTINCT FROM k.vehicle_id
                               AND r.company_id IS NOT DISTINCT FROM k.company_id
              LEFT JOIN damage d ON d.period = k.period
                               AND d.vehicle_id IS NOT DISTINCT FROM k.vehicle_id
                               AND d.company_id IS NOT DISTINCT FROM k.company_id
              LEFT JOIN fuel fu ON fu.period = k.period
                               AND fu.vehicle_id IS NOT DISTINCT FROM k.vehicle_id
                               AND fu.company_id IS NOT DISTINCT FROM k.company_id
              LEFT JOIN service s ON s.period = k.period
                               AND s.vehicle_id IS NOT DISTINCT FROM k.vehicle_id
                               AND s.company_id IS NOT DISTINCT FROM k.company_id
        """
