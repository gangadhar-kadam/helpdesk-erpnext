# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe.utils import flt, cint

from frappe import msgprint, _
import frappe.defaults
from frappe.model.mapper import get_mapped_doc
from erpnext.controllers.selling_controller import SellingController
from frappe.desk.notifications import clear_doctype_notifications


form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

class DeliveryNote(SellingController):
	def __init__(self, arg1, arg2=None):
		super(DeliveryNote, self).__init__(arg1, arg2)
		self.status_updater = [{
			'source_dt': 'Delivery Note Item',
			'target_dt': 'Sales Order Item',
			'join_field': 'so_detail',
			'target_field': 'delivered_qty',
			'target_parent_dt': 'Sales Order',
			'target_parent_field': 'per_delivered',
			'target_ref_field': 'qty',
			'source_field': 'qty',
			'percent_join_field': 'against_sales_order',
			'status_field': 'delivery_status',
			'keyword': 'Delivered',
			'second_source_dt': 'Sales Invoice Item',
			'second_source_field': 'qty',
			'second_join_field': 'so_detail',
			'overflow_type': 'delivery',
			'second_source_extra_cond': """ and exists(select name from `tabSales Invoice`
				where name=`tabSales Invoice Item`.parent and update_stock = 1)"""
		},
		{
			'source_dt': 'Delivery Note Item',
			'target_dt': 'Sales Invoice Item',
			'join_field': 'si_detail',
			'target_field': 'delivered_qty',
			'target_parent_dt': 'Sales Invoice',
			'target_ref_field': 'qty',
			'source_field': 'qty',
			'percent_join_field': 'against_sales_invoice',
			'overflow_type': 'delivery'
		},
		{
			'source_dt': 'Delivery Note Item',
			'target_dt': 'Sales Order Item',
			'join_field': 'so_detail',
			'target_field': 'returned_qty',
			'target_parent_dt': 'Sales Order',
			# 'target_parent_field': 'per_delivered',
			# 'target_ref_field': 'qty',
			'source_field': '-1 * qty',
			# 'percent_join_field': 'against_sales_order',
			# 'overflow_type': 'delivery',
			'extra_cond': """ and exists (select name from `tabDelivery Note` where name=`tabDelivery Note Item`.parent and is_return=1)"""
		}]

	def onload(self):
		billed_qty = frappe.db.sql("""select sum(qty) from `tabSales Invoice Item`
			where docstatus=1 and delivery_note=%s""", self.name)
		if billed_qty:
			total_qty = sum((item.qty for item in self.get("items")))
			self.set_onload("billing_complete", (billed_qty[0][0] == total_qty))
			
		self.set_onload("has_return_entry", len(frappe.db.exists({"doctype": "Delivery Note", 
			"is_return": 1, "return_against": self.name, "docstatus": 1})))

	def before_print(self):
		def toggle_print_hide(meta, fieldname):
			df = meta.get_field(fieldname)
			if self.get("print_without_amount"):
				df.set("__print_hide", 1)
			else:
				df.delete_key("__print_hide")

		item_meta = frappe.get_meta("Delivery Note Item")
		print_hide_fields = {
			"parent": ["grand_total", "rounded_total", "in_words", "currency", "total", "taxes"],
			"items": ["rate", "amount", "price_list_rate", "discount_percentage"]
		}

		for key, fieldname in print_hide_fields.items():
			for f in fieldname:
				toggle_print_hide(self.meta if key == "parent" else item_meta, f)

	def set_actual_qty(self):
		for d in self.get('items'):
			if d.item_code and d.warehouse:
				actual_qty = frappe.db.sql("""select actual_qty from `tabBin`
					where item_code = %s and warehouse = %s""", (d.item_code, d.warehouse))
				d.actual_qty = actual_qty and flt(actual_qty[0][0]) or 0

	def so_required(self):
		"""check in manage account if sales order required or not"""
		if frappe.db.get_value("Selling Settings", None, 'so_required') == 'Yes':
			 for d in self.get('items'):
				 if not d.against_sales_order:
					 frappe.throw(_("Sales Order required for Item {0}").format(d.item_code))

	def validate(self):
		super(DeliveryNote, self).validate()
		self.set_status()
		self.so_required()
		self.validate_proj_cust()
		self.check_stop_or_close_sales_order("against_sales_order")
		self.validate_for_items()
		self.validate_warehouse()
		self.validate_uom_is_integer("stock_uom", "qty")
		self.validate_with_previous_doc()

		from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
		make_packing_list(self)

		self.update_current_stock()

		if not self.installation_status: self.installation_status = 'Not Installed'

	def validate_with_previous_doc(self):
		for fn in (("Sales Order", "against_sales_order", "so_detail"),
				("Sales Invoice", "against_sales_invoice", "si_detail")):
			if filter(None, [getattr(d, fn[1], None) for d in self.get("items")]):
				super(DeliveryNote, self).validate_with_previous_doc({
					fn[0]: {
						"ref_dn_field": fn[1],
						"compare_fields": [["customer", "="], ["company", "="], ["project_name", "="],
							["currency", "="]],
					},
				})

		if cint(frappe.db.get_single_value('Selling Settings', 'maintain_same_sales_rate')) and not self.is_return:
			self.validate_rate_with_reference_doc([["Sales Order", "sales_order", "so_detail"],
				["Sales Invoice", "sales_invoice", "si_detail"]])

	def validate_proj_cust(self):
		"""check for does customer belong to same project as entered.."""
		if self.project_name and self.customer:
			res = frappe.db.sql("""select name from `tabProject`
				where name = %s and (customer = %s or
					ifnull(customer,'')='')""", (self.project_name, self.customer))
			if not res:
				frappe.throw(_("Customer {0} does not belong to project {1}").format(self.customer, self.project_name))

	def validate_for_items(self):
		check_list, chk_dupl_itm = [], []
		if cint(frappe.db.get_single_value("Selling Settings", "allow_multiple_items")):
			return

		for d in self.get('items'):
			e = [d.item_code, d.description, d.warehouse, d.against_sales_order or d.against_sales_invoice, d.batch_no or '']
			f = [d.item_code, d.description, d.against_sales_order or d.against_sales_invoice]

			if frappe.db.get_value("Item", d.item_code, "is_stock_item") == 1:
				if e in check_list:
					msgprint(_("Note: Item {0} entered multiple times").format(d.item_code))
				else:
					check_list.append(e)
			else:
				if f in chk_dupl_itm:
					msgprint(_("Note: Item {0} entered multiple times").format(d.item_code))
				else:
					chk_dupl_itm.append(f)

	def validate_warehouse(self):
		super(DeliveryNote, self).validate_warehouse()
		
		for d in self.get_item_list():
			if frappe.db.get_value("Item", d['item_code'], "is_stock_item") == 1:
				if not d['warehouse']:
					frappe.throw(_("Warehouse required for stock Item {0}").format(d["item_code"]))


	def update_current_stock(self):
		if self.get("_action") and self._action != "update_after_submit":
			for d in self.get('items'):
				d.actual_qty = frappe.db.get_value("Bin", {"item_code": d.item_code,
					"warehouse": d.warehouse}, "actual_qty")

			for d in self.get('packed_items'):
				bin_qty = frappe.db.get_value("Bin", {"item_code": d.item_code,
					"warehouse": d.warehouse}, ["actual_qty", "projected_qty"], as_dict=True)
				if bin_qty:
					d.actual_qty = flt(bin_qty.actual_qty)
					d.projected_qty = flt(bin_qty.projected_qty)

	def on_submit(self):
		self.validate_packed_qty()

		# Check for Approving Authority
		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype, self.company, self.base_grand_total, self)

		# update delivered qty in sales order
		self.update_prevdoc_status()

		if not self.is_return:
			self.check_credit_limit()

		self.update_stock_ledger()
		self.make_gl_entries()

		frappe.db.set(self, 'status', 'Submitted')


	def on_cancel(self):
		self.check_stop_or_close_sales_order("against_sales_order")
		self.check_next_docstatus()

		self.update_prevdoc_status()

		self.update_stock_ledger()

		frappe.db.set(self, 'status', 'Cancelled')
		self.cancel_packing_slips()

		self.make_gl_entries_on_cancel()

	def check_credit_limit(self):
		from erpnext.selling.doctype.customer.customer import check_credit_limit

		validate_against_credit_limit = False
		for d in self.get("items"):
			if not (d.against_sales_order or d.against_sales_invoice):
				validate_against_credit_limit = True
				break
		if validate_against_credit_limit:
			check_credit_limit(self.customer, self.company)

	def validate_packed_qty(self):
		"""
			Validate that if packed qty exists, it should be equal to qty
		"""
		if not any([flt(d.get('packed_qty')) for d in self.get("items")]):
			return
		has_error = False
		for d in self.get("items"):
			if flt(d.get('qty')) != flt(d.get('packed_qty')):
				frappe.msgprint(_("Packed quantity must equal quantity for Item {0} in row {1}").format(d.item_code, d.idx))
				has_error = True
		if has_error:
			raise frappe.ValidationError

	def check_next_docstatus(self):
		submit_rv = frappe.db.sql("""select t1.name
			from `tabSales Invoice` t1,`tabSales Invoice Item` t2
			where t1.name = t2.parent and t2.delivery_note = %s and t1.docstatus = 1""",
			(self.name))
		if submit_rv:
			frappe.throw(_("Sales Invoice {0} has already been submitted").format(submit_rv[0][0]))

		submit_in = frappe.db.sql("""select t1.name
			from `tabInstallation Note` t1, `tabInstallation Note Item` t2
			where t1.name = t2.parent and t2.prevdoc_docname = %s and t1.docstatus = 1""",
			(self.name))
		if submit_in:
			frappe.throw(_("Installation Note {0} has already been submitted").format(submit_in[0][0]))

	def cancel_packing_slips(self):
		"""
			Cancel submitted packing slips related to this delivery note
		"""
		res = frappe.db.sql("""SELECT name FROM `tabPacking Slip` WHERE delivery_note = %s
			AND docstatus = 1""", self.name)

		if res:
			for r in res:
				ps = frappe.get_doc('Packing Slip', r[0])
				ps.cancel()
			frappe.msgprint(_("Packing Slip(s) cancelled"))

	def update_status(self, status):
		self.set_status(update=True, status=status)
		self.notify_update()
		clear_doctype_notifications(self)

def get_list_context(context=None):
	from erpnext.controllers.website_list_for_contact import get_list_context
	list_context = get_list_context(context)
	list_context["title"] = _("My Shipments")
	return list_context

def get_invoiced_qty_map(delivery_note):
	"""returns a map: {dn_detail: invoiced_qty}"""
	invoiced_qty_map = {}

	for dn_detail, qty in frappe.db.sql("""select dn_detail, qty from `tabSales Invoice Item`
		where delivery_note=%s and docstatus=1""", delivery_note):
			if not invoiced_qty_map.get(dn_detail):
				invoiced_qty_map[dn_detail] = 0
			invoiced_qty_map[dn_detail] += qty

	return invoiced_qty_map

@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):
	invoiced_qty_map = get_invoiced_qty_map(source_name)

	def update_accounts(source, target):
		target.is_pos = 0
		target.ignore_pricing_rule = 1
		target.run_method("set_missing_values")

		if len(target.get("items")) == 0:
			frappe.throw(_("All these items have already been invoiced"))

		target.run_method("calculate_taxes_and_totals")

	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty = source_doc.qty - invoiced_qty_map.get(source_doc.name, 0)

	doc = get_mapped_doc("Delivery Note", source_name, 	{
		"Delivery Note": {
			"doctype": "Sales Invoice",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Delivery Note Item": {
			"doctype": "Sales Invoice Item",
			"field_map": {
				"name": "dn_detail",
				"parent": "delivery_note",
				"so_detail": "so_detail",
				"against_sales_order": "sales_order",
				"serial_no": "serial_no"
			},
			"postprocess": update_item,
			"filter": lambda d: abs(d.qty) - abs(invoiced_qty_map.get(d.name, 0))<=0
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
	}, target_doc, update_accounts)

	return doc

@frappe.whitelist()
def make_installation_note(source_name, target_doc=None):
	def update_item(obj, target, source_parent):
		target.qty = flt(obj.qty) - flt(obj.installed_qty)
		target.serial_no = obj.serial_no

	doclist = get_mapped_doc("Delivery Note", source_name, 	{
		"Delivery Note": {
			"doctype": "Installation Note",
			"validation": {
				"docstatus": ["=", 1]
			}
		},
		"Delivery Note Item": {
			"doctype": "Installation Note Item",
			"field_map": {
				"name": "prevdoc_detail_docname",
				"parent": "prevdoc_docname",
				"parenttype": "prevdoc_doctype",
			},
			"postprocess": update_item,
			"condition": lambda doc: doc.installed_qty < doc.qty
		}
	}, target_doc)

	return doclist

@frappe.whitelist()
def make_packing_slip(source_name, target_doc=None):
	doclist = get_mapped_doc("Delivery Note", source_name, 	{
		"Delivery Note": {
			"doctype": "Packing Slip",
			"field_map": {
				"name": "delivery_note",
				"letter_head": "letter_head"
			},
			"validation": {
				"docstatus": ["=", 0]
			}
		}
	}, target_doc)

	return doclist


@frappe.whitelist()
def make_sales_return(source_name, target_doc=None):
	from erpnext.controllers.sales_and_purchase_return import make_return_doc
	return make_return_doc("Delivery Note", source_name, target_doc)


@frappe.whitelist()
def update_delivery_note_status(docname, status):
	dn = frappe.get_doc("Delivery Note", docname)
	dn.update_status(status)
