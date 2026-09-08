# -*- coding: utf-8 -*-
from . import models

# قواعد أودو المفتوحة [(1,'=',1)] على مجموعات المحاسبة. لا يكفي إضافة
# قاعدة مقيِّدة بجانبها: قواعد المجموعات تُدمَج بـOR فتُبطلها هذه تماماً
# (تحقّقنا عملياً: قواعد الدفاتر عملت لأن لا قاعدة مفتوحة عليها، بينما
# لم تعمل قواعد القيود والبنود إطلاقاً).
#
# ولا يكفي تعديلها من XML أيضاً: سجلاتها الأصلية داخل كتلة
# <data noupdate="1"> في موديول account، فأي <record> يستهدفها يُتجاهَل
# بصمت تام (لا خطأ ولا تحذير) - وهذا بالضبط ما حدث في أول محاولة.
# الحل الوحيد الموثوق: تعديلها برمجياً عند التثبيت، وإعادتها عند
# الإلغاء (وإلا بقيت تشير لحقل team_ids المحذوف فتتعطل المحاسبة كلياً).
_PATCHED_RULES = (
    'account.account_move_see_all',
    'account.account_move_rule_group_invoice',
    'account.account_move_rule_group_readonly',
    'account.account_move_line_see_all',
    'account.account_move_line_rule_group_invoice',
    'account.account_move_line_rule_group_readonly',
)

_TEAM_DOMAIN = (
    "['|', ('journal_id.team_ids', '=', False),"
    " ('journal_id.team_ids', 'in', user.accounting_team_ids.ids)]"
)
_OPEN_DOMAIN = "[(1, '=', 1)]"


def _set_rules_domain(env, domain):
    for xmlid in _PATCHED_RULES:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.sudo().domain_force = domain


def _apply_team_rules(env):
    """يجعل قواعد أودو المفتوحة مدرِكة للفريق المحاسبي - تُستدعى من
    post_init_hook (عند التثبيت) ومن account.team.init() (عند كل
    تحديث)، فلا يبقى الموديول مثبَّتاً بلا أثر فعلي أبداً."""
    _set_rules_domain(env, _TEAM_DOMAIN)


def post_init_hook(env):
    _apply_team_rules(env)


def uninstall_hook(env):
    """يعيد قواعد أودو إلى مجالها الأصلي المفتوح."""
    _set_rules_domain(env, _OPEN_DOMAIN)
