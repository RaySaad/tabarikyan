# -*- coding: utf-8 -*-
from odoo import fields, models


class FleetEmployeeCostReport(models.Model):
    """كم كلّفني هذا المندوب في الأسطول؟

    البيانات موجودة عندك لكنها مبعثرة: الوقود في سجل التعبئات،
    والتلفيات في بلاغات الحوادث، والمطالبات والمخالفات في السداد
    البنكي، وأجرة مركبته في التحميل الشهري. هذا العرض يجمعها على
    المندوب شهراً بشهر.

    مهم في القراءة: **أجرة المركبة تكلفة على الفرع لا على المندوب** -
    عُرضت هنا في عمود مستقل لتعرف كلفة تشغيله الكاملة، ولا تُجمع مع
    ما يُطالَب به شخصياً.
    """
    _name = 'fleet.employee.cost.report'
    _description = 'تكلفة المندوب في الأسطول'
    _auto = False
    _order = 'period desc, total_cost desc'

    period = fields.Date(string='الشهر', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='المندوب', readonly=True)
    company_id = fields.Many2one('res.company', string='الفرع', readonly=True)

    fuel_amount = fields.Float(string='الوقود', readonly=True)
    fuel_liters = fields.Float(string='اللترات', readonly=True)
    damage_amount = fields.Float(string='تلفيات بمسؤوليته', readonly=True)
    accident_count = fields.Integer(string='عدد الحوادث', readonly=True)
    claim_amount = fields.Float(string='مطالبات ومخالفات', readonly=True)
    rent_amount = fields.Float(string='أجرة مركبته (على الفرع)', readonly=True)
    total_cost = fields.Float(string='إجمالي ما يخصّه', readonly=True)

    @property
    def _table_query(self):
        return """
            WITH fuel AS (
                SELECT date_trunc('month', f.date)::date AS period,
                       f.driver_id AS employee_id,
                       f.company_id,
                       SUM(f.amount) AS fuel_amount,
                       SUM(f.liters) AS fuel_liters
                  FROM fleet_fuel_log f
                 WHERE f.driver_id IS NOT NULL
                 GROUP BY 1, 2, 3
            ), damage AS (
                -- ما يتحمله المندوب شخصياً من تكلفة الإصلاح، لا كامل
                -- التكلفة: الباقي على الأسطول أو التأمين.
                SELECT date_trunc('month', a.close_date)::date AS period,
                       a.employee_id,
                       a.company_id,
                       SUM(COALESCE(a.actual_cost, 0.0)
                           * COALESCE(a.employee_share_percent, 0.0) / 100.0)
                           AS damage_amount,
                       COUNT(*) AS accident_count
                  FROM fleet_accident_report a
                 WHERE a.employee_id IS NOT NULL
                   AND a.close_date IS NOT NULL
                 GROUP BY 1, 2, 3
            ), claims AS (
                -- مطالبات السداد البنكي على المندوب (مخالفات، أضرار،
                -- وقود مدفوع عنه...) - المعتمَدة والمنفَّذة فقط.
                SELECT date_trunc('month',
                           COALESCE(t.transfer_date, t.create_date::date))::date AS period,
                       t.employee_id,
                       t.company_id,
                       SUM(COALESCE(t.amount, 0.0)) AS claim_amount
                  FROM bank_settlement_vehicle_transfer t
                 WHERE t.employee_id IS NOT NULL
                   AND t.state IN ('confirmed', 'done')
                 GROUP BY 1, 2, 3
            ), rent AS (
                SELECT date_trunc('month', c.period_date)::date AS period,
                       ct.employee_id,
                       c.company_id,
                       SUM(l.amount) AS rent_amount
                  FROM fleet_branch_rental_charge_line l
                  JOIN fleet_branch_rental_charge c ON c.id = l.charge_id
                  JOIN fleet_rental_contract ct ON ct.id = l.contract_id
                 WHERE l.line_type = 'rent'
                   AND c.state != 'cancel'
                   AND ct.employee_id IS NOT NULL
                 GROUP BY 1, 2, 3
            ), keys AS (
                SELECT period, employee_id, company_id FROM fuel
                UNION SELECT period, employee_id, company_id FROM damage
                UNION SELECT period, employee_id, company_id FROM claims
                UNION SELECT period, employee_id, company_id FROM rent
            )
            SELECT row_number() OVER () AS id,
                   k.period,
                   k.employee_id,
                   k.company_id,
                   COALESCE(f.fuel_amount, 0.0) AS fuel_amount,
                   COALESCE(f.fuel_liters, 0.0) AS fuel_liters,
                   COALESCE(d.damage_amount, 0.0) AS damage_amount,
                   COALESCE(d.accident_count, 0) AS accident_count,
                   COALESCE(cl.claim_amount, 0.0) AS claim_amount,
                   COALESCE(r.rent_amount, 0.0) AS rent_amount,
                   -- ما يخصّ المندوب: وقوده + تلفياته + مطالباته.
                   -- الأجرة على الفرع فلا تدخل الإجمالي.
                   COALESCE(f.fuel_amount, 0.0) + COALESCE(d.damage_amount, 0.0)
                       + COALESCE(cl.claim_amount, 0.0) AS total_cost
              FROM keys k
              LEFT JOIN fuel f ON f.period = k.period
                               AND f.employee_id IS NOT DISTINCT FROM k.employee_id
                               AND f.company_id IS NOT DISTINCT FROM k.company_id
              LEFT JOIN damage d ON d.period = k.period
                               AND d.employee_id IS NOT DISTINCT FROM k.employee_id
                               AND d.company_id IS NOT DISTINCT FROM k.company_id
              LEFT JOIN claims cl ON cl.period = k.period
                               AND cl.employee_id IS NOT DISTINCT FROM k.employee_id
                               AND cl.company_id IS NOT DISTINCT FROM k.company_id
              LEFT JOIN rent r ON r.period = k.period
                               AND r.employee_id IS NOT DISTINCT FROM k.employee_id
                               AND r.company_id IS NOT DISTINCT FROM k.company_id
        """
