# -*- coding: utf-8 -*-
import json

from . import models

# ---------------------------------------------------------------------
# كل القواعد التي تمنح رؤية القيود/الفواتير في أودو، والتي يجعلها هذا
# الموديول خاضعة للفريق المحاسبي.
#
# لماذا التعديل بدل الإضافة: قواعد السجلات المرتبطة بمجموعات تُدمَج
# بينها بـOR لا AND - فأي قاعدة مقيِّدة تُضاف بجانب قاعدة مفتوحة تُبطَل
# تماماً. ولماذا برمجياً لا من XML: هذه السجلات داخل كتل
# <data noupdate="1"> فيُتجاهَل أي <record> يستهدفها بصمت تام.
#
# المجموعة الأولى (account): قواعد مفتوحة [(1,'=',1)] لكل من يملك أي
# صلاحية محاسبية.
# المجموعة الثانية (sale/purchase): تمنح الرؤية حسب *نوع* الفاتورة -
# فواتير العملاء لمن يملك صلاحية مبيعات، وفواتير الموردين لمن يملك
# صلاحية مشتريات - بغض النظر عن الدفتر. وهي السبب الفعلي في بقاء
# مستخدم يرى فواتير خارج فرقه رغم تقييد كل الدفاتر بفرق.
# المجموعة الثالثة (السطور التحليلية): قاعدتان مفتوحتان كانتا تكشفان
# التوزيع التحليلي لقيود دفاتر أخرى - أي تكلفة كل منصة.
#
# ونماذج لا تمرّ بقواعد account.move إطلاقاً (account.payment و
# account.bank.statement) تُغطّى بقواعد جديدة في
# security/account_team_security.xml لا بالتعديل هنا، إذ لا توجد قاعدة
# مفتوحة تُبطلها.
# ---------------------------------------------------------------------
# شرط الفريق: الدفتر بلا فريق مرئي للجميع، أو أن يكون أحد فرق الدفتر
# ضمن فرق المستخدم. يُدمَج مع مجال القاعدة الأصلي بجمع القائمتين، فينتج
# AND ضمني بين الشرطين: ما كانت القاعدة تسمح به *وأيضاً* ضمن فرق
# المستخدم.
_TEAM_DOMAIN = (
    "['|', ('journal_id.team_ids', '=', False),"
    " ('journal_id.team_ids', 'in', user.accounting_team_ids.ids)]"
)

# السطر التحليلي وحده قد لا يرتبط بقيد محاسبي إطلاقاً (سطور الحضور
# والمشاريع مثلاً، وحقل journal_id فيه related عن move_line_id ويكون
# فارغاً حينها). فبلا الفرع الأول كانت القاعدة تُخفي تلك السطور عن
# المحاسبين كافة - تقييد لم نطلبه ويكسر شاشات خارج المحاسبة.
_ANALYTIC_TEAM_DOMAIN = (
    "['|', ('journal_id', '=', False),"
    " '|', ('journal_id.team_ids', '=', False),"
    " ('journal_id.team_ids', 'in', user.accounting_team_ids.ids)]"
)


_RULES = {}

# قواعد يرتبط سجلها بالدفتر مباشرةً عبر journal_id (وهو حقل مطلوب فيها
# كلها، فلا وجود لسجل بلا دفتر).
for _xmlid in (
    'account.account_move_see_all',
    'account.account_move_rule_group_invoice',
    'account.account_move_rule_group_readonly',
    'account.account_move_line_see_all',
    'account.account_move_line_rule_group_invoice',
    'account.account_move_line_rule_group_readonly',
    'sale.account_invoice_rule_see_all',
    'sale.account_invoice_rule_see_personal',
    'sale.account_invoice_line_rule_see_all',
    'sale.account_invoice_line_rule_see_personal',
    'purchase.purchase_user_account_move_rule',
    'purchase.purchase_user_account_move_line_rule',
    # قاعدة السداد البنكي: كانت تُظهر *كل* قيود السداد البنكي في أي دفتر
    # لمن يملك صلاحية السداد - فتفتح ما أغلقته الفرق تماماً (رسوم
    # حكومية، سلف، تأمين طبي، واستحقاقات الدفعات المقدمة). أُخضعت
    # للفريق بقرار صريح: الدفتر هو المرجع الوحيد، ومن ليس ضمن فريق
    # الدفتر لا يرى قيوده مهما كانت صلاحياته الأخرى.
    'bank_settlement.account_move_bank_settlement_rule',
):
    _RULES[_xmlid] = _TEAM_DOMAIN

# السطور التحليلية: أودو تشحن عليها قاعدتين مفتوحتين [(1,'=',1)] فكان
# المحاسب المقيَّد يرى التوزيع التحليلي لقيود دفاتر ليست من فرقه - وهي
# أخطر تسريب في هذا النظام تحديداً، إذ تحمل تكلفة كل منصة على حدة.
for _xmlid in (
    'account.account_analytic_line_rule_billing_user',
    'account.account_analytic_line_rule_readonly_user',
):
    _RULES[_xmlid] = _ANALYTIC_TEAM_DOMAIN


# مستثناة عمداً (وليست سهواً):
# - account.account_invoice_rule_portal (والبنود): تخص العملاء على
#   البوابة الإلكترونية - كل عميل يرى فواتيره هو، ولا علاقة للفرق
#   المحاسبية بذلك؛ تقييدها يمنع العميل من رؤية فاتورته.
#
# ملاحظة تشغيلية مهمة بعد إخضاع قاعدة السداد البنكي للفريق: موظفو
# السداد البنكي (وهم ليسوا محاسبين) يحتاجون الانضمام لفريق يضم دفاترهم
# (الراجحي/المدفوعات الحكومية) ليتمكنوا من فتح زر "القيد المحاسبي" من
# شاشاتهم - وسجلات السداد نفسها تبقى مرئية لهم كاملة بلا أي تأثر،
# فالتقييد على القيود المحاسبية وحدها.

# نسخة احتياطية من المجالات الأصلية - تُؤخذ مرة واحدة عند أول تعديل،
# فتُستعاد حرفياً عند إلغاء التثبيت بدل تخمين ما كانت عليه (وهو يختلف
# بين إصدارات أودو وحسب الموديولات المثبَّتة).
_BACKUP_PARAM = 'accounting_teams.original_rule_domains'


_TEAM_MARKER = 'journal_id.team_ids'


def _apply_team_rules(env):
    """يجعل كل قواعد رؤية القيود خاضعة للفريق المحاسبي.

    idempotent: تُبنى كل مرة من المجال الأصلي المحفوظ لا من الحالي،
    فتكرار الاستدعاء لا يراكم الشرط. ولا تكتب شيئاً إن كانت القاعدة
    مضبوطة أصلاً - فاستدعاؤها عند كل تحميل للسجل (registry) رخيص."""
    params = env['ir.config_parameter'].sudo()
    backup = json.loads(params.get_param(_BACKUP_PARAM) or '{}')
    changed = False
    for xmlid, team_domain in _RULES.items():
        rule = env.ref(xmlid, raise_if_not_found=False)
        if not rule:
            continue  # الموديول المصدر غير مثبَّت (مبيعات/مشتريات مثلاً)
        current = rule.domain_force or ''
        if _TEAM_MARKER in current:
            continue  # مضبوطة بالفعل
        # المجال الحالي هو الأصل (لم يُعدَّل بعد، أو أعاده تحديث موديوله)
        backup[xmlid] = current
        rule.sudo().domain_force = '%s + %s' % (current, team_domain)
        changed = True
    if changed:
        params.set_param(_BACKUP_PARAM, json.dumps(backup))


def post_init_hook(env):
    _apply_team_rules(env)


def uninstall_hook(env):
    """يعيد كل قاعدة لمجالها الأصلي المحفوظ حرفياً - وإلا بقيت بعد
    الإلغاء تشير لحقل team_ids المحذوف فتتعطل المحاسبة بالكامل."""
    params = env['ir.config_parameter'].sudo()
    backup = json.loads(params.get_param(_BACKUP_PARAM) or '{}')
    for xmlid, original in backup.items():
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.sudo().domain_force = original
    params.set_param(_BACKUP_PARAM, '{}')
