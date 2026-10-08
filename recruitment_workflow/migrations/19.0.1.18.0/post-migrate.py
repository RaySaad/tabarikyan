# -*- coding: utf-8 -*-
"""يصحّح شركة السجلات القديمة لتتبع شركة الموظف لا شركة من أنشأها.

كانت كل هذه النماذج تأخذ الشركة من مبدِّل الشركات لحظة الإنشاء
(``default=lambda self: self.env.company``)، فسجّل من يعمل في فرع
طلباتِ موظفي فروع أخرى على فرعه هو. وعلى هذه النماذج قاعدة عزل
``company_id in company_ids`` - فالسجل المسجَّل خطأً مخفيٌّ الآن عن
فرع صاحبه. هذا الترحيل يعيد كل سجل إلى فرع موظفه فيظهر لأهله.

يُصحَّح بـSQL مباشرةً: تحديث حقل انتماء لا منطق فيه (لا آثار جانبية
ولا تتبُّع يعني أحداً في سجل قديم)، والجداول قد تكون كبيرة.
"""
import logging

_logger = logging.getLogger(__name__)

# الجدول -> (عمود الموظف، عمود بديل اختياري لمركبة)
_TABLES = {
    'hr_employee_platform_transfer_request': ('employee_id', None),
    'hr_employee_exit_request': ('employee_id', None),
    'hr_employee_warning': ('employee_id', None),
    'hr_employee_platform_history': ('employee_id', None),
    'fleet_vehicle_change_request': ('employee_id', 'current_vehicle_id'),
    'fleet_accident_report': ('employee_id', 'vehicle_id'),
}


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", ('public.%s' % table,))
    return bool(cr.fetchone()[0])


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    total = 0
    for table, (emp_col, vehicle_col) in _TABLES.items():
        if not _table_exists(cr, table) or not _column_exists(cr, table, 'company_id'):
            continue

        # ١) من شركة الموظف
        cr.execute("""
            UPDATE {table} t
               SET company_id = e.company_id
              FROM hr_employee e
             WHERE t.{emp} = e.id
               AND e.company_id IS NOT NULL
               AND t.company_id IS DISTINCT FROM e.company_id
        """.format(table=table, emp=emp_col))
        moved = cr.rowcount

        # ٢) ما لا موظف له (بلاغ حادث بلا سائق مثلاً) يتبع فرع مركبته
        if vehicle_col and _column_exists(cr, table, vehicle_col):
            cr.execute("""
                UPDATE {table} t
                   SET company_id = v.company_id
                  FROM fleet_vehicle v
                 WHERE t.{veh} = v.id
                   AND t.{emp} IS NULL
                   AND v.company_id IS NOT NULL
                   AND t.company_id IS DISTINCT FROM v.company_id
            """.format(table=table, veh=vehicle_col, emp=emp_col))
            moved += cr.rowcount

        total += moved
        if moved:
            _logger.info('تصحيح الشركة: %s -> %d سجلاً', table, moved)
    _logger.info('إجمالي السجلات التي أُعيدت لفرع موظفها: %d', total)
