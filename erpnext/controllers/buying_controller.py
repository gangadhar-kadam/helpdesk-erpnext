# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import _, msgprint
from frappe.utils import flt

from erpnext.setup.utils import get_company_currency
from erpnext.accounts.party import get_party_details
from erpnext.stock.get_item_details import get_conversion_factor

from erpnext.controllers.stock_controller import StockController

class BuyingController(StockController):
	def __setup__(self):
		if hasattr(self, "taxes"):
			self.print_templates = {
				"taxes": "templates/print_formats/includes/taxes.html"
			}

	def get_feed(self):
		return _("From {0} | {1} {2}").format(self.supplier_name, self.currency,
			self.grand_total)

	def validate(self):
		super(BuyingController, self).validate()
		if getattr(self, "supplier", None) and not self.supplier_name:
			self.supplier_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name")
		self.is_item_table_empty()
		self.set_qty_as_per_stock_uom()
		self.validate_stock_or_nonstock_items()
		self.validate_warehouse()

	def set_missing_values(self, for_validate=False):
		super(BuyingController, self).set_missing_values(for_validate)

		self.set_supplier_from_item_default()
		self.set_price_list_currency("Buying")

		# set contact and address details for supplier, if they are not mentioned
		if getattr(self, "supplier", None):
			self.update_if_missing(get_party_details(self.supplier, party_type="Supplier"))

		self.set_missing_item_details()

	def set_supplier_from_item_default(self):
		if self.meta.get_field("supplier") and not self.supplier:
			for d in self.get("items"):
				supplier = frappe.db.get_value("Item", d.item_code, "default_supplier")
				if supplier:
					self.supplier = supplier
					break

	def validate_stock_or_nonstock_items(self):
		if self.meta.get_field("taxes") and not self.get_stock_items():
			tax_for_valuation = [d.account_head for d in self.get("taxes")
				if d.category in ["Valuation", "Valuation and Total"]]
			if tax_for_valuation:
				frappe.throw(_("Tax Category can not be 'Valuation' or 'Valuation and Total' as all items are non-stock items"))

	def set_total_in_words(self):
		from frappe.utils import money_in_words
		company_currency = get_company_currency(self.company)
		if self.meta.get_field("base_in_words"):
			self.base_in_words = money_in_words(self.base_grand_total, company_currency)
		if self.meta.get_field("in_words"):
			self.in_words = money_in_words(self.grand_total, self.currency)

	# update valuation rate
	def update_valuation_rate(self, parentfield):
		"""
			item_tax_amount is the total tax amount applied on that item
			stored for valuation

			TODO: rename item_tax_amount to valuation_tax_amount
		"""
		stock_items = self.get_stock_items()

		stock_items_qty, stock_items_amount = 0, 0
		last_stock_item_idx = 1
		for d in self.get(parentfield):
			if d.item_code and d.item_code in stock_items:
				stock_items_qty += flt(d.qty)
				stock_items_amount += flt(d.base_net_amount)
				last_stock_item_idx = d.idx

		total_valuation_amount = sum([flt(d.base_tax_amount_after_discount_amount) for d in self.get("taxes")
			if d.category in ["Valuation", "Valuation and Total"]])

		valuation_amount_adjustment = total_valuation_amount
		for i, item in enumerate(self.get(parentfield)):
			if item.item_code and item.qty and item.item_code in stock_items:
				item_proportion = flt(item.base_net_amount) / stock_items_amount if stock_items_amount \
					else flt(item.qty) / stock_items_qty

				if i == (last_stock_item_idx - 1):
					item.item_tax_amount = flt(valuation_amount_adjustment,
						self.precision("item_tax_amount", item))
				else:
					item.item_tax_amount = flt(item_proportion * total_valuation_amount,
						self.precision("item_tax_amount", item))
					valuation_amount_adjustment -= item.item_tax_amount

				self.round_floats_in(item)
				if flt(item.conversion_factor)==0:
					item.conversion_factor = get_conversion_factor(item.item_code, item.uom).get("conversion_factor") or 1.0

				qty_in_stock_uom = flt(item.qty * item.conversion_factor)
				rm_supp_cost = flt(item.rm_supp_cost) if self.doctype=="Purchase Receipt" else 0.0

				landed_cost_voucher_amount = flt(item.landed_cost_voucher_amount) \
					if self.doctype == "Purchase Receipt" else 0.0

				item.valuation_rate = ((item.base_net_amount + item.item_tax_amount + rm_supp_cost
					 + landed_cost_voucher_amount) / qty_in_stock_uom)
			else:
				item.valuation_rate = 0.0

	def validate_for_subcontracting(self):
		if not self.is_subcontracted and self.sub_contracted_items:
			frappe.throw(_("Please enter 'Is Subcontracted' as Yes or No"))

		if self.is_subcontracted == "Yes":
			if self.doctype == "Purchase Receipt" and not self.supplier_warehouse:
				frappe.throw(_("Supplier Warehouse mandatory for sub-contracted Purchase Receipt"))

			for item in self.get("items"):
				if item in self.sub_contracted_items and not item.bom:
					frappe.throw(_("Please select BOM in BOM field for Item {0}").format(item.item_code))

		else:
			for item in self.get("items"):
				if item.bom:
					item.bom = None

	def create_raw_materials_supplied(self, raw_material_table):
		if self.is_subcontracted=="Yes":
			parent_items = []
			for item in self.get("items"):
				if self.doctype == "Purchase Receipt":
					item.rm_supp_cost = 0.0
				if item.item_code in self.sub_contracted_items:
					self.update_raw_materials_supplied(item, raw_material_table)

					if [item.item_code, item.name] not in parent_items:
						parent_items.append([item.item_code, item.name])

			self.cleanup_raw_materials_supplied(parent_items, raw_material_table)

		elif self.doctype == "Purchase Receipt":
			for item in self.get("items"):
				item.rm_supp_cost = 0.0

	def update_raw_materials_supplied(self, item, raw_material_table):
		bom_items = self.get_items_from_bom(item.item_code, item.bom)
		raw_materials_cost = 0

		for bom_item in bom_items:
			# check if exists
			exists = 0
			for d in self.get(raw_material_table):
				if d.main_item_code == item.item_code and d.rm_item_code == bom_item.item_code \
					and d.reference_name == item.name:
						rm, exists = d, 1
						break

			if not exists:
				rm = self.append(raw_material_table, {})

			required_qty = flt(bom_item.qty_consumed_per_unit) * flt(item.qty) * flt(item.conversion_factor)
			rm.reference_name = item.name
			rm.bom_detail_no = bom_item.name
			rm.main_item_code = item.item_code
			rm.rm_item_code = bom_item.item_code
			rm.stock_uom = bom_item.stock_uom
			rm.required_qty = required_qty

			rm.conversion_factor = item.conversion_factor

			if self.doctype == "Purchase Receipt":
				rm.consumed_qty = required_qty
				rm.description = bom_item.description
				if item.batch_no and not rm.batch_no:
					rm.batch_no = item.batch_no

			# get raw materials rate
			if self.doctype == "Purchase Receipt":
				from erpnext.stock.utils import get_incoming_rate
				rm.rate = get_incoming_rate({
					"item_code": bom_item.item_code,
					"warehouse": self.supplier_warehouse,
					"posting_date": self.posting_date,
					"posting_time": self.posting_time,
					"qty": -1 * required_qty,
					"serial_no": rm.serial_no
				})
				if not rm.rate:
					from erpnext.stock.stock_ledger import get_valuation_rate
					rm.rate = get_valuation_rate(bom_item.item_code, self.supplier_warehouse)
			else:
				rm.rate = bom_item.rate

			rm.amount = required_qty * flt(rm.rate)
			raw_materials_cost += flt(rm.amount)

		if self.doctype == "Purchase Receipt":
			item.rm_supp_cost = raw_materials_cost

	def cleanup_raw_materials_supplied(self, parent_items, raw_material_table):
		"""Remove all those child items which are no longer present in main item table"""
		delete_list = []
		for d in self.get(raw_material_table):
			if [d.main_item_code, d.reference_name] not in parent_items:
				# mark for deletion from doclist
				delete_list.append(d)

		# delete from doclist
		if delete_list:
			rm_supplied_details = self.get(raw_material_table)
			self.set(raw_material_table, [])
			for d in rm_supplied_details:
				if d not in delete_list:
					self.append(raw_material_table, d)

	def get_items_from_bom(self, item_code, bom):
		bom_items = frappe.db.sql("""select t2.item_code,
			t2.qty / ifnull(t1.quantity, 1) as qty_consumed_per_unit,
			t2.rate, t2.stock_uom, t2.name, t2.description
			from `tabBOM` t1, `tabBOM Item` t2, tabItem t3
			where t2.parent = t1.name and t1.item = %s
			and t1.docstatus = 1 and t1.is_active = 1 and t1.name = %s
			and t2.item_code = t3.name and t3.is_stock_item = 1""", (item_code, bom), as_dict=1)

		if not bom_items:
			msgprint(_("Specified BOM {0} does not exist for Item {1}").format(bom, item_code), raise_exception=1)

		return bom_items

	@property
	def sub_contracted_items(self):
		if not hasattr(self, "_sub_contracted_items"):
			self._sub_contracted_items = []
			item_codes = list(set(item.item_code for item in
				self.get("items")))
			if item_codes:
				self._sub_contracted_items = [r[0] for r in frappe.db.sql("""select name
					from `tabItem` where name in (%s) and is_sub_contracted_item=1""" % \
					(", ".join((["%s"]*len(item_codes))),), item_codes)]

		return self._sub_contracted_items

	@property
	def purchase_items(self):
		if not hasattr(self, "_purchase_items"):
			self._purchase_items = []
			item_codes = list(set(item.item_code for item in
				self.get("items")))
			if item_codes:
				self._purchase_items = [r[0] for r in frappe.db.sql("""select name
					from `tabItem` where name in (%s) and is_purchase_item='Yes'""" % \
					(", ".join((["%s"]*len(item_codes))),), item_codes)]

		return self._purchase_items

	def is_item_table_empty(self):
		if not len(self.get("items")):
			frappe.throw(_("Item table can not be blank"))

	def set_qty_as_per_stock_uom(self):
		for d in self.get("items"):
			if d.meta.get_field("stock_qty"):
				if not d.conversion_factor:
					frappe.throw(_("Row {0}: Conversion Factor is mandatory").format(d.idx))
				d.stock_qty = flt(d.qty) * flt(d.conversion_factor)
