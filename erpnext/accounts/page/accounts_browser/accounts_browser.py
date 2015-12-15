# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
import frappe.defaults
from frappe.utils import flt
from erpnext.accounts.utils import get_balance_on
from erpnext.accounts.report.financial_statements import sort_root_accounts

@frappe.whitelist()
def get_companies():
	"""get a list of companies based on permission"""
	return [d.name for d in frappe.get_list("Company", fields=["name"],
		order_by="name")]

@frappe.whitelist()
def get_children():
	args = frappe.local.form_dict
	ctype, company = args['ctype'], args['comp']

	# root
	if args['parent'] in ("Accounts", "Cost Centers"):
		select_cond = ", root_type, report_type, account_currency" if ctype=="Account" else ""
		acc = frappe.db.sql(""" select
			name as value, is_group as expandable %s
			from `tab%s`
			where ifnull(`parent_%s`,'') = ''
			and `company` = %s	and docstatus<2
			order by name""" % (select_cond, frappe.db.escape(ctype), frappe.db.escape(ctype.lower().replace(' ','_')), '%s'),
				company, as_dict=1)

		if args["parent"]=="Accounts":
			sort_root_accounts(acc)
	else:
		# other
		select_cond = ", account_currency" if ctype=="Account" else ""
		acc = frappe.db.sql("""select
			name as value, is_group as expandable %s
	 		from `tab%s`
			where ifnull(`parent_%s`,'') = %s
			and docstatus<2
			order by name""" % (select_cond, frappe.db.escape(ctype), frappe.db.escape(ctype.lower().replace(' ','_')), '%s'),
				args['parent'], as_dict=1)

	if ctype == 'Account':
		company_currency = frappe.db.get_value("Company", company, "default_currency")
		for each in acc:
			each["company_currency"] = company_currency
			each["balance"] = flt(get_balance_on(each.get("value"), in_account_currency=False))
			
			if each.account_currency != company_currency:
				each["balance_in_account_currency"] = flt(get_balance_on(each.get("value")))

	return acc
