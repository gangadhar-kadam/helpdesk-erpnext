# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
import frappe.defaults
from frappe.utils import cint, flt
from frappe import _, msgprint, throw
from erpnext.accounts.party import get_party_account, get_due_date
from erpnext.controllers.stock_controller import update_gl_entries_after
from frappe.model.mapper import get_mapped_doc

from erpnext.controllers.selling_controller import SellingController
from erpnext.accounts.utils import get_account_currency

form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

class SalesInvoice(SellingController):
	def __init__(self, arg1, arg2=None):
		super(SalesInvoice, self).__init__(arg1, arg2)
		self.status_updater = [{
			'source_dt': 'Sales Invoice Item',
			'target_field': 'billed_amt',
			'target_ref_field': 'amount',
			'target_dt': 'Sales Order Item',
			'join_field': 'so_detail',
			'target_parent_dt': 'Sales Order',
			'target_parent_field': 'per_billed',
			'source_field': 'amount',
			'join_field': 'so_detail',
			'percent_join_field': 'sales_order',
			'status_field': 'billing_status',
			'keyword': 'Billed',
			'overflow_type': 'billing'
		}]

	def set_indicator(self):
		"""Set indicator for portal"""
		if self.outstanding_amount > 0:
			self.indicator_color = "orange"
			self.indicator_title = _("Unpaid")
		else:
			self.indicator_color = "green"
			self.indicator_title = _("Paid")

	def validate(self):
		super(SalesInvoice, self).validate()
		self.validate_posting_time()
		self.so_dn_required()
		self.validate_proj_cust()
		self.validate_with_previous_doc()
		self.validate_uom_is_integer("stock_uom", "qty")
		self.check_stop_or_close_sales_order("sales_order")
		self.validate_debit_to_acc()
		self.validate_fixed_asset_account()
		self.clear_unallocated_advances("Sales Invoice Advance", "advances")
		self.validate_advance_jv("Sales Order")
		self.add_remarks()
		self.validate_write_off_account()

		if cint(self.is_pos):
			self.validate_pos()

		if cint(self.update_stock):
			self.validate_dropship_item()
			self.validate_item_code()
			self.validate_warehouse()
			self.update_current_stock()
			self.validate_delivery_note()

		if not self.is_opening:
			self.is_opening = 'No'

		self.set_against_income_account()
		self.validate_c_form()
		self.validate_time_logs_are_submitted()
		self.validate_multiple_billing("Delivery Note", "dn_detail", "amount", "items")
		self.update_packing_list()

	def on_submit(self):
		super(SalesInvoice, self).on_submit()

		if cint(self.update_stock) == 1:
			self.update_stock_ledger()
		else:
			# Check for Approving Authority
			if not self.recurring_id:
				frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
				 	self.company, self.base_grand_total, self)

		self.check_prev_docstatus()

		if self.is_return:
			# NOTE status updating bypassed for is_return
			self.status_updater = []

		self.update_status_updater_args()
		self.update_prevdoc_status()

		# this sequence because outstanding may get -ve
		self.make_gl_entries()

		if not self.is_return:
			self.update_billing_status_for_zero_amount_refdoc("Sales Order")
			self.check_credit_limit()

		if not cint(self.is_pos) == 1 and not self.is_return:
			self.update_against_document_in_jv()

		self.update_time_log_batch(self.name)

	def before_cancel(self):
		self.update_time_log_batch(None)

	def on_cancel(self):
		if cint(self.update_stock) == 1:
			self.update_stock_ledger()

		self.check_stop_or_close_sales_order("sales_order")

		from erpnext.accounts.utils import remove_against_link_from_jv
		remove_against_link_from_jv(self.doctype, self.name)

		if self.is_return:
			# NOTE status updating bypassed for is_return
			self.status_updater = []

		self.update_status_updater_args()
		self.update_prevdoc_status()

		if not self.is_return:
			self.update_billing_status_for_zero_amount_refdoc("Sales Order")

		self.validate_c_form_on_cancel()

		self.make_gl_entries_on_cancel()

	def update_status_updater_args(self):
		if cint(self.update_stock):
			self.status_updater.extend([{
				'source_dt':'Sales Invoice Item',
				'target_dt':'Sales Order Item',
				'target_parent_dt':'Sales Order',
				'target_parent_field':'per_delivered',
				'target_field':'delivered_qty',
				'target_ref_field':'qty',
				'source_field':'qty',
				'join_field':'so_detail',
				'percent_join_field':'sales_order',
				'status_field':'delivery_status',
				'keyword':'Delivered',
				'second_source_dt': 'Delivery Note Item',
				'second_source_field': 'qty',
				'second_join_field': 'so_detail',
				'overflow_type': 'delivery',
				'extra_cond': """ and exists(select name from `tabSales Invoice`
					where name=`tabSales Invoice Item`.parent and update_stock = 1)"""
			},
			{
				'source_dt': 'Sales Invoice Item',
				'target_dt': 'Sales Order Item',
				'join_field': 'so_detail',
				'target_field': 'returned_qty',
				'target_parent_dt': 'Sales Order',
				# 'target_parent_field': 'per_delivered',
				# 'target_ref_field': 'qty',
				'source_field': '-1 * qty',
				# 'percent_join_field': 'sales_order',
				# 'overflow_type': 'delivery',
				'extra_cond': """ and exists (select name from `tabSales Invoice` where name=`tabSales Invoice Item`.parent and update_stock=1 and is_return=1)"""
			}
		])

	def check_credit_limit(self):
		from erpnext.selling.doctype.customer.customer import check_credit_limit

		validate_against_credit_limit = False
		for d in self.get("items"):
			if not (d.sales_order or d.delivery_note):
				validate_against_credit_limit = True
				break
		if validate_against_credit_limit:
			check_credit_limit(self.customer, self.company)

	def set_missing_values(self, for_validate=False):
		pos = self.set_pos_fields(for_validate)

		if not self.debit_to:
			self.debit_to = get_party_account("Customer", self.customer, self.company)
		if not self.due_date and self.customer:
			self.due_date = get_due_date(self.posting_date, "Customer", self.customer, self.company)

		super(SalesInvoice, self).set_missing_values(for_validate)

		if pos:
			return {"print_format": pos.get("print_format") }

	def update_time_log_batch(self, sales_invoice):
		for d in self.get("items"):
			if d.time_log_batch:
				tlb = frappe.get_doc("Time Log Batch", d.time_log_batch)
				tlb.sales_invoice = sales_invoice
				tlb.flags.ignore_validate_update_after_submit = True
				tlb.save()

	def validate_time_logs_are_submitted(self):
		for d in self.get("items"):
			if d.time_log_batch:
				docstatus = frappe.db.get_value("Time Log Batch", d.time_log_batch, "docstatus")
				if docstatus!=1:
					frappe.throw(_("Time Log Batch {0} must be 'Submitted'").format(d.time_log_batch))

	def set_pos_fields(self, for_validate=False):
		"""Set retail related fields from POS Profiles"""
		if cint(self.is_pos) != 1:
			return

		from erpnext.stock.get_item_details import get_pos_profile_item_details, get_pos_profile
		pos = get_pos_profile(self.company)

		if pos:
			if not for_validate and not self.customer:
				self.customer = pos.customer
				self.mode_of_payment = pos.mode_of_payment
				# self.set_customer_defaults()

			for fieldname in ('territory', 'naming_series', 'currency', 'taxes_and_charges', 'letter_head', 'tc_name',
				'selling_price_list', 'company', 'select_print_heading', 'cash_bank_account',
				'write_off_account', 'write_off_cost_center'):
					if (not for_validate) or (for_validate and not self.get(fieldname)):
						self.set(fieldname, pos.get(fieldname))

			if not for_validate:
				self.update_stock = cint(pos.get("update_stock"))

			# set pos values in items
			for item in self.get("items"):
				if item.get('item_code'):
					for fname, val in get_pos_profile_item_details(pos,
						frappe._dict(item.as_dict()), pos).items():

						if (not for_validate) or (for_validate and not item.get(fname)):
							item.set(fname, val)

			# fetch terms
			if self.tc_name and not self.terms:
				self.terms = frappe.db.get_value("Terms and Conditions", self.tc_name, "terms")

			# fetch charges
			if self.taxes_and_charges and not len(self.get("taxes")):
				self.set_taxes()

		return pos

	def get_advances(self):
		if not self.is_return:
			super(SalesInvoice, self).get_advances(self.debit_to, "Customer", self.customer,
				"Sales Invoice Advance", "advances", "credit_in_account_currency", "sales_order")

	def get_company_abbr(self):
		return frappe.db.sql("select abbr from tabCompany where name=%s", self.company)[0][0]

	def update_against_document_in_jv(self):
		"""
			Links invoice and advance voucher:
				1. cancel advance voucher
				2. split into multiple rows if partially adjusted, assign against voucher
				3. submit advance voucher
		"""

		lst = []
		for d in self.get('advances'):
			if flt(d.allocated_amount) > 0:
				args = {
					'voucher_no' : d.journal_entry,
					'voucher_detail_no' : d.jv_detail_no,
					'against_voucher_type' : 'Sales Invoice',
					'against_voucher'  : self.name,
					'account' : self.debit_to,
					'party_type': 'Customer',
					'party': self.customer,
					'is_advance' : 'Yes',
					'dr_or_cr' : 'credit_in_account_currency',
					'unadjusted_amt' : flt(d.advance_amount),
					'allocated_amt' : flt(d.allocated_amount)
				}
				lst.append(args)

		if lst:
			from erpnext.accounts.utils import reconcile_against_document
			reconcile_against_document(lst)

	def validate_debit_to_acc(self):
		account = frappe.db.get_value("Account", self.debit_to,
			["account_type", "report_type", "account_currency"], as_dict=True)

		if account.report_type != "Balance Sheet":
			frappe.throw(_("Debit To account must be a Balance Sheet account"))

		if self.customer and account.account_type != "Receivable":
			frappe.throw(_("Debit To account must be a Receivable account"))

		self.party_account_currency = account.account_currency

	def validate_fixed_asset_account(self):
		"""Validate Fixed Asset and whether Income Account Entered Exists"""
		for d in self.get('items'):
			is_asset_item = frappe.db.get_value("Item", d.item_code, "is_asset_item")
			account_type = frappe.db.get_value("Account", d.income_account, "account_type")
			if is_asset_item == 1 and account_type != 'Fixed Asset':
				msgprint(_("Account {0} must be of type 'Fixed Asset' as Item {1} is an Asset Item").format(d.income_account, d.item_code), raise_exception=True)

	def validate_with_previous_doc(self):
		super(SalesInvoice, self).validate_with_previous_doc({
			"Sales Order": {
				"ref_dn_field": "sales_order",
				"compare_fields": [["customer", "="], ["company", "="], ["project_name", "="],
					["currency", "="]],
			},
			"Delivery Note": {
				"ref_dn_field": "delivery_note",
				"compare_fields": [["customer", "="], ["company", "="], ["project_name", "="],
					["currency", "="]],
			},
		})

		if cint(frappe.db.get_single_value('Selling Settings', 'maintain_same_sales_rate')) and not self.is_return:
			self.validate_rate_with_reference_doc([
				["Sales Order", "sales_order", "so_detail"],
				["Delivery Note", "delivery_note", "dn_detail"]
			])

	def set_against_income_account(self):
		"""Set against account for debit to account"""
		against_acc = []
		for d in self.get('items'):
			if d.income_account not in against_acc:
				against_acc.append(d.income_account)
		self.against_income_account = ','.join(against_acc)


	def add_remarks(self):
		if not self.remarks: self.remarks = 'No Remarks'


	def so_dn_required(self):
		"""check in manage account if sales order / delivery note required or not."""
		dic = {'Sales Order':'so_required','Delivery Note':'dn_required'}
		for i in dic:
			if frappe.db.get_value('Selling Settings', None, dic[i]) == 'Yes':
				for d in self.get('items'):
					if frappe.db.get_value('Item', d.item_code, 'is_stock_item') == 1 \
						and not d.get(i.lower().replace(' ','_')):
						msgprint(_("{0} is mandatory for Item {1}").format(i,d.item_code), raise_exception=1)


	def validate_proj_cust(self):
		"""check for does customer belong to same project as entered.."""
		if self.project_name and self.customer:
			res = frappe.db.sql("""select name from `tabProject`
				where name = %s and (customer = %s or customer is null or customer = '')""",
				(self.project_name, self.customer))
			if not res:
				throw(_("Customer {0} does not belong to project {1}").format(self.customer,self.project_name))

	def validate_pos(self):
		if not self.cash_bank_account and flt(self.paid_amount):
			frappe.throw(_("Cash or Bank Account is mandatory for making payment entry"))

		if flt(self.paid_amount) + flt(self.write_off_amount) \
				- flt(self.base_grand_total) > 1/(10**(self.precision("base_grand_total") + 1)):
			frappe.throw(_("""Paid amount + Write Off Amount can not be greater than Grand Total"""))


	def validate_item_code(self):
		for d in self.get('items'):
			if not d.item_code:
				msgprint(_("Item Code required at Row No {0}").format(d.idx), raise_exception=True)

	def validate_warehouse(self):
		super(SalesInvoice, self).validate_warehouse()
		
		for d in self.get('items'):
			if not d.warehouse:
				frappe.throw(_("Warehouse required at Row No {0}").format(d.idx))

	def validate_delivery_note(self):
		for d in self.get("items"):
			if d.delivery_note:
				msgprint(_("Stock cannot be updated against Delivery Note {0}").format(d.delivery_note), raise_exception=1)


	def validate_write_off_account(self):
		if flt(self.write_off_amount) and not self.write_off_account:
			msgprint(_("Please enter Write Off Account"), raise_exception=1)


	def validate_c_form(self):
		""" Blank C-form no if C-form applicable marked as 'No'"""
		if self.amended_from and self.c_form_applicable == 'No' and self.c_form_no:
			frappe.db.sql("""delete from `tabC-Form Invoice Detail` where invoice_no = %s
					and parent = %s""", (self.amended_from,	self.c_form_no))

			frappe.db.set(self, 'c_form_no', '')

	def validate_c_form_on_cancel(self):
		""" Display message if C-Form no exists on cancellation of Sales Invoice"""
		if self.c_form_applicable == 'Yes' and self.c_form_no:
			msgprint(_("Please remove this Invoice {0} from C-Form {1}")
				.format(self.name, self.c_form_no), raise_exception = 1)
	
	def validate_dropship_item(self):
		for item in self.items:
			if item.sales_order:
				if frappe.db.get_value("Sales Order Item", item.so_detail, "delivered_by_supplier"):
					frappe.throw(_("Could not update stock, invoice contains drop shipping item."))

	def update_current_stock(self):
		for d in self.get('items'):
			if d.item_code and d.warehouse:
				bin = frappe.db.sql("select actual_qty from `tabBin` where item_code = %s and warehouse = %s", (d.item_code, d.warehouse), as_dict = 1)
				d.actual_qty = bin and flt(bin[0]['actual_qty']) or 0

		for d in self.get('packed_items'):
			bin = frappe.db.sql("select actual_qty, projected_qty from `tabBin` where item_code =	%s and warehouse = %s", (d.item_code, d.warehouse), as_dict = 1)
			d.actual_qty = bin and flt(bin[0]['actual_qty']) or 0
			d.projected_qty = bin and flt(bin[0]['projected_qty']) or 0

	def update_packing_list(self):
		if cint(self.update_stock) == 1:
			from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
			make_packing_list(self)
		else:
			self.set('packed_items', [])


	def get_warehouse(self):
		user_pos_profile = frappe.db.sql("""select name, warehouse from `tabPOS Profile`
			where ifnull(user,'') = %s and company = %s""", (frappe.session['user'], self.company))
		warehouse = user_pos_profile[0][1] if user_pos_profile else None

		if not warehouse:
			global_pos_profile = frappe.db.sql("""select name, warehouse from `tabPOS Profile`
				where (user is null or user = '') and company = %s""", self.company)

			if global_pos_profile:
				warehouse = global_pos_profile[0][1]
			elif not user_pos_profile:
				msgprint(_("POS Profile required to make POS Entry"), raise_exception=True)

		return warehouse

	def on_update(self):
		if cint(self.is_pos) == 1:
			if flt(self.paid_amount) == 0:
				if self.cash_bank_account:
					frappe.db.set(self, 'paid_amount',
						flt(flt(self.grand_total) - flt(self.write_off_amount), self.precision("paid_amount")))
				else:
					# show message that the amount is not paid
					frappe.db.set(self,'paid_amount',0)
					frappe.msgprint(_("Note: Payment Entry will not be created since 'Cash or Bank Account' was not specified"))
		else:
			frappe.db.set(self,'paid_amount',0)

		frappe.db.set(self, 'base_paid_amount',
			flt(self.paid_amount*self.conversion_rate, self.precision("base_paid_amount")))

	def check_prev_docstatus(self):
		for d in self.get('items'):
			if d.sales_order and frappe.db.get_value("Sales Order", d.sales_order, "docstatus") != 1:
				frappe.throw(_("Sales Order {0} is not submitted").format(d.sales_order))

			if d.delivery_note and frappe.db.get_value("Delivery Note", d.delivery_note, "docstatus") != 1:
				throw(_("Delivery Note {0} is not submitted").format(d.delivery_note))

	def make_gl_entries(self, repost_future_gle=True):
		gl_entries = self.get_gl_entries()

		if gl_entries:
			from erpnext.accounts.general_ledger import make_gl_entries

			# if POS and amount is written off, updating outstanding amt after posting all gl entries
			update_outstanding = "No" if (cint(self.is_pos) or self.write_off_account) else "Yes"

			make_gl_entries(gl_entries, cancel=(self.docstatus == 2),
				update_outstanding=update_outstanding, merge_entries=False)

			if update_outstanding == "No":
				from erpnext.accounts.doctype.gl_entry.gl_entry import update_outstanding_amt
				update_outstanding_amt(self.debit_to, "Customer", self.customer,
					self.doctype, self.return_against if cint(self.is_return) else self.name)

			if repost_future_gle and cint(self.update_stock) \
				and cint(frappe.defaults.get_global_default("auto_accounting_for_stock")):
					items, warehouses = self.get_items_and_warehouses()
					update_gl_entries_after(self.posting_date, self.posting_time, warehouses, items)
		elif self.docstatus == 2 and cint(self.update_stock) \
			and cint(frappe.defaults.get_global_default("auto_accounting_for_stock")):
				from erpnext.accounts.general_ledger import delete_gl_entries
				delete_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def get_gl_entries(self, warehouse_account=None):
		from erpnext.accounts.general_ledger import merge_similar_entries

		gl_entries = []

		self.make_customer_gl_entry(gl_entries)

		self.make_tax_gl_entries(gl_entries)

		self.make_item_gl_entries(gl_entries)

		# merge gl entries before adding pos entries
		gl_entries = merge_similar_entries(gl_entries)

		self.make_pos_gl_entries(gl_entries)

		self.make_write_off_gl_entry(gl_entries)

		return gl_entries

	def make_customer_gl_entry(self, gl_entries):
		if self.grand_total:
			gl_entries.append(
				self.get_gl_dict({
					"account": self.debit_to,
					"party_type": "Customer",
					"party": self.customer,
					"against": self.against_income_account,
					"debit": self.base_grand_total,
					"debit_in_account_currency": self.base_grand_total \
						if self.party_account_currency==self.company_currency else self.grand_total,
					"against_voucher": self.return_against if cint(self.is_return) else self.name,
					"against_voucher_type": self.doctype
				}, self.party_account_currency)
			)

	def make_tax_gl_entries(self, gl_entries):
		for tax in self.get("taxes"):
			if flt(tax.base_tax_amount_after_discount_amount):
				account_currency = get_account_currency(tax.account_head)
				gl_entries.append(
					self.get_gl_dict({
						"account": tax.account_head,
						"against": self.customer,
						"credit": flt(tax.base_tax_amount_after_discount_amount),
						"credit_in_account_currency": flt(tax.base_tax_amount_after_discount_amount) \
							if account_currency==self.company_currency else flt(tax.tax_amount_after_discount_amount),
						"cost_center": tax.cost_center
					}, account_currency)
				)

	def make_item_gl_entries(self, gl_entries):
		# income account gl entries
		for item in self.get("items"):
			if flt(item.base_net_amount):
				account_currency = get_account_currency(item.income_account)
				gl_entries.append(
					self.get_gl_dict({
						"account": item.income_account,
						"against": self.customer,
						"credit": item.base_net_amount,
						"credit_in_account_currency": item.base_net_amount \
							if account_currency==self.company_currency else item.net_amount,
						"cost_center": item.cost_center
					}, account_currency)
				)

		# expense account gl entries
		if cint(frappe.defaults.get_global_default("auto_accounting_for_stock")) \
				and cint(self.update_stock):
			gl_entries += super(SalesInvoice, self).get_gl_entries()

	def make_pos_gl_entries(self, gl_entries):
		if cint(self.is_pos) and self.cash_bank_account and self.paid_amount:
			bank_account_currency = get_account_currency(self.cash_bank_account)
			# POS, make payment entries
			gl_entries.append(
				self.get_gl_dict({
					"account": self.debit_to,
					"party_type": "Customer",
					"party": self.customer,
					"against": self.cash_bank_account,
					"credit": self.base_paid_amount,
					"credit_in_account_currency": self.base_paid_amount \
						if self.party_account_currency==self.company_currency else self.paid_amount,
					"against_voucher": self.return_against if cint(self.is_return) else self.name,
					"against_voucher_type": self.doctype,
				}, self.party_account_currency)
			)
			gl_entries.append(
				self.get_gl_dict({
					"account": self.cash_bank_account,
					"against": self.customer,
					"debit": self.base_paid_amount,
					"debit_in_account_currency": self.base_paid_amount \
						if bank_account_currency==self.company_currency else self.paid_amount
				}, bank_account_currency)
			)

	def make_write_off_gl_entry(self, gl_entries):
		# write off entries, applicable if only pos
		if self.write_off_account and self.write_off_amount:
			write_off_account_currency = get_account_currency(self.write_off_account)

			gl_entries.append(
				self.get_gl_dict({
					"account": self.debit_to,
					"party_type": "Customer",
					"party": self.customer,
					"against": self.write_off_account,
					"credit": self.base_write_off_amount,
					"credit_in_account_currency": self.base_write_off_amount \
						if self.party_account_currency==self.company_currency else self.write_off_amount,
					"against_voucher": self.return_against if cint(self.is_return) else self.name,
					"against_voucher_type": self.doctype
				}, self.party_account_currency)
			)
			gl_entries.append(
				self.get_gl_dict({
					"account": self.write_off_account,
					"against": self.customer,
					"debit": self.base_write_off_amount,
					"debit_in_account_currency": self.base_write_off_amount \
						if write_off_account_currency==self.company_currency else self.write_off_amount,
					"cost_center": self.write_off_cost_center
				}, write_off_account_currency)
			)

def get_list_context(context=None):
	from erpnext.controllers.website_list_for_contact import get_list_context
	list_context = get_list_context(context)
	list_context["title"] = _("My Invoices")
	return list_context

@frappe.whitelist()
def get_bank_cash_account(mode_of_payment, company):
	account = frappe.db.get_value("Mode of Payment Account",
		{"parent": mode_of_payment, "company": company}, "default_account")
	if not account:
		frappe.msgprint(_("Please set default Cash or Bank account in Mode of Payment {0}").format(mode_of_payment))
	return {
		"account": account
	}

@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None):
	def set_missing_values(source, target):
		target.ignore_pricing_rule = 1
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source_doc, target_doc, source_parent):
		target_doc.base_amount = (flt(source_doc.qty) - flt(source_doc.delivered_qty)) * \
			flt(source_doc.base_rate)
		target_doc.amount = (flt(source_doc.qty) - flt(source_doc.delivered_qty)) * \
			flt(source_doc.rate)
		target_doc.qty = flt(source_doc.qty) - flt(source_doc.delivered_qty)

	doclist = get_mapped_doc("Sales Invoice", source_name, 	{
		"Sales Invoice": {
			"doctype": "Delivery Note",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Sales Invoice Item": {
			"doctype": "Delivery Note Item",
			"field_map": {
				"name": "si_detail",
				"parent": "against_sales_invoice",
				"serial_no": "serial_no",
				"sales_order": "against_sales_order",
				"so_detail": "so_detail"
			},
			"postprocess": update_item,
			"condition": lambda doc: doc.delivered_by_supplier!=1
		},
		"Sales Taxes and Charges": {
			"doctype": "Sales Taxes and Charges",
			"add_if_empty": True
		},
		"Sales Team": {
			"doctype": "Sales Team",
			"field_map": {
				"incentives": "incentives"
			},
			"add_if_empty": True
		}
	}, target_doc, set_missing_values)

	return doclist


@frappe.whitelist()
def make_sales_return(source_name, target_doc=None):
	from erpnext.controllers.sales_and_purchase_return import make_return_doc
	return make_return_doc("Sales Invoice", source_name, target_doc)
