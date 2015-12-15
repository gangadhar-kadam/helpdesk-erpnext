# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cint, cstr, flt

from frappe import _
from frappe.model.document import Document

from operator import itemgetter

class BOM(Document):

	def autoname(self):
		last_name = frappe.db.sql("""select max(name) from `tabBOM`
			where name like "BOM/%s/%%" """ % frappe.db.escape(self.item))
		if last_name:
			idx = cint(cstr(last_name[0][0]).split('/')[-1].split('-')[0]) + 1
		else:
			idx = 1
		self.name = 'BOM/' + self.item + ('/%.3i' % idx)

	def validate(self):
		self.clear_operations()
		self.validate_main_item()

		from erpnext.utilities.transaction_base import validate_uom_is_integer
		validate_uom_is_integer(self, "stock_uom", "qty", "BOM Item")

		self.validate_materials()
		self.set_bom_material_details()
		self.calculate_cost()
		self.validate_operations()

	def on_update(self):
		self.check_recursion()
		self.update_exploded_items()

	def on_submit(self):
		self.manage_default_bom()

	def on_cancel(self):
		frappe.db.set(self, "is_active", 0)
		frappe.db.set(self, "is_default", 0)

		# check if used in any other bom
		self.validate_bom_links()
		self.manage_default_bom()

	def on_update_after_submit(self):
		self.validate_bom_links()
		self.manage_default_bom()

	def get_item_det(self, item_code):
		item = frappe.db.sql("""select name, item_name, is_asset_item, is_purchase_item,
			docstatus, description, image, is_sub_contracted_item, stock_uom, default_bom,
			last_purchase_rate
			from `tabItem` where name=%s""", item_code, as_dict = 1)

		if not item:
			frappe.throw(_("Item: {0} does not exist in the system").format(item_code))

		return item

	def validate_rm_item(self, item):
		if item[0]['name'] == self.item:
			frappe.throw(_("Raw material cannot be same as main Item"))

	def set_bom_material_details(self):
		for item in self.get("items"):
			ret = self.get_bom_material_detail({"item_code": item.item_code, "item_name": item.item_name, "bom_no": item.bom_no,
				"qty": item.qty})

			for r in ret:
				if not item.get(r):
					item.set(r, ret[r])

	def get_bom_material_detail(self, args=None):
		""" Get raw material details like uom, desc and rate"""
		if not args:
			args = frappe.form_dict.get('args')

		if isinstance(args, basestring):
			import json
			args = json.loads(args)

		item = self.get_item_det(args['item_code'])
		self.validate_rm_item(item)

		args['bom_no'] = args['bom_no'] or item and cstr(item[0]['default_bom']) or ''
		args.update(item[0])

		rate = self.get_rm_rate(args)
		ret_item = {
			 'item_name'	: item and args['item_name'] or '',
			 'description'  : item and args['description'] or '',
			 'image'		: item and args['image'] or '',
			 'stock_uom'	: item and args['stock_uom'] or '',
			 'bom_no'		: args['bom_no'],
			 'rate'			: rate
		}
		return ret_item

	def get_rm_rate(self, arg):
		"""	Get raw material rate as per selected method, if bom exists takes bom cost """
		rate = 0
		if arg['bom_no']:
			rate = self.get_bom_unitcost(arg['bom_no'])
		elif arg and (arg['is_purchase_item'] == 1 or arg['is_sub_contracted_item'] == 1):
			if self.rm_cost_as_per == 'Valuation Rate':
				rate = self.get_valuation_rate(arg)
			elif self.rm_cost_as_per == 'Last Purchase Rate':
				rate = arg['last_purchase_rate']
			elif self.rm_cost_as_per == "Price List":
				if not self.buying_price_list:
					frappe.throw(_("Please select Price List"))
				rate = frappe.db.get_value("Item Price", {"price_list": self.buying_price_list,
					"item_code": arg["item_code"]}, "price_list_rate") or 0

		return rate

	def update_cost(self):
		if self.docstatus == 2:
			return

		for d in self.get("items"):
			rate = self.get_bom_material_detail({'item_code': d.item_code, 'bom_no': d.bom_no,
				'qty': d.qty})["rate"]
			if rate:
				d.rate = rate

		if self.docstatus == 1:
			self.flags.ignore_validate_update_after_submit = True
			self.calculate_cost()
		self.save()
		self.update_exploded_items()

		frappe.msgprint(_("Cost Updated"))

	def get_bom_unitcost(self, bom_no):
		bom = frappe.db.sql("""select name, total_cost/quantity as unit_cost from `tabBOM`
			where is_active = 1 and name = %s""", bom_no, as_dict=1)
		return bom and bom[0]['unit_cost'] or 0

	def get_valuation_rate(self, args):
		""" Get weighted average of valuation rate from all warehouses """

		total_qty, total_value, valuation_rate = 0.0, 0.0, 0.0
		for d in frappe.db.sql("""select actual_qty, stock_value from `tabBin`
			where item_code=%s""", args['item_code'], as_dict=1):
				total_qty += flt(d.actual_qty)
				total_value += flt(d.stock_value)

		if total_qty:
			valuation_rate =  total_value / total_qty

		if valuation_rate <= 0:
			last_valuation_rate = frappe.db.sql("""select valuation_rate
				from `tabStock Ledger Entry`
				where item_code = %s and valuation_rate > 0
				order by posting_date desc, posting_time desc, name desc limit 1""", args['item_code'])

			valuation_rate = flt(last_valuation_rate[0][0]) if last_valuation_rate else 0

		return valuation_rate

	def manage_default_bom(self):
		""" Uncheck others if current one is selected as default,
			update default bom in item master
		"""
		if self.is_default and self.is_active:
			from frappe.model.utils import set_default
			set_default(self, "item")
			item = frappe.get_doc("Item", self.item)
			if item.default_bom != self.name:
				item.default_bom = self.name
				item.save()
		else:
			frappe.db.set(self, "is_default", 0)
			item = frappe.get_doc("Item", self.item)
			if item.default_bom == self.name:
				item.default_bom = None
				item.save()

	def clear_operations(self):
		if not self.with_operations:
			self.set('operations', [])

	def validate_main_item(self):
		""" Validate main FG item"""
		item = self.get_item_det(self.item)
		if not item:
			frappe.throw(_("Item {0} does not exist in the system or has expired").format(self.item))
		else:
			ret = frappe.db.get_value("Item", self.item, ["description", "stock_uom", "item_name"])
			self.description = ret[0]
			self.uom = ret[1]
			self.item_name= ret[2]

	def validate_materials(self):
		""" Validate raw material entries """
		if not self.get('items'):
			frappe.throw(_("Raw Materials cannot be blank."))
		check_list = []
		for m in self.get('items'):
			if m.bom_no:
				validate_bom_no(m.item_code, m.bom_no)
			if flt(m.qty) <= 0:
				frappe.throw(_("Quantity required for Item {0} in row {1}").format(m.item_code, m.idx))
			check_list.append(cstr(m.item_code))
		unique_chk_list = set(check_list)
		if len(unique_chk_list)	!= len(check_list):
			frappe.throw(_("Same item has been entered multiple times."))

	def check_recursion(self):
		""" Check whether recursion occurs in any bom"""

		check_list = [['parent', 'bom_no', 'parent'], ['bom_no', 'parent', 'child']]
		for d in check_list:
			bom_list, count = [self.name], 0
			while (len(bom_list) > count ):
				boms = frappe.db.sql(" select %s from `tabBOM Item` where %s = %s " %
					(d[0], d[1], '%s'), cstr(bom_list[count]))
				count = count + 1
				for b in boms:
					if b[0] == self.name:
						frappe.throw(_("BOM recursion: {0} cannot be parent or child of {2}").format(b[0], self.name))
					if b[0]:
						bom_list.append(b[0])

	def update_cost_and_exploded_items(self, bom_list=[]):
		bom_list = self.traverse_tree(bom_list)
		for bom in bom_list:
			bom_obj = frappe.get_doc("BOM", bom)
			bom_obj.on_update()

		return bom_list

	def traverse_tree(self, bom_list=[]):
		def _get_children(bom_no):
			return [cstr(d[0]) for d in frappe.db.sql("""select bom_no from `tabBOM Item`
				where parent = %s and ifnull(bom_no, '') != ''""", bom_no)]

		count = 0
		if self.name not in bom_list:
			bom_list.append(self.name)

		while(count < len(bom_list)):
			for child_bom in _get_children(bom_list[count]):
				if child_bom not in bom_list:
					bom_list.append(child_bom)
			count += 1
		bom_list.reverse()
		return bom_list

	def calculate_cost(self):
		"""Calculate bom totals"""
		self.calculate_op_cost()
		self.calculate_rm_cost()
		self.total_cost = self.operating_cost + self.raw_material_cost

	def calculate_op_cost(self):
		"""Update workstation rate and calculates totals"""
		self.operating_cost = 0
		for d in self.get('operations'):
			if d.workstation:
				if not d.hour_rate:
					d.hour_rate = flt(frappe.db.get_value("Workstation", d.workstation, "hour_rate"))

			if d.hour_rate and d.time_in_mins:
				d.operating_cost = flt(d.hour_rate) * flt(d.time_in_mins) / 60.0

			self.operating_cost += flt(d.operating_cost)

	def calculate_rm_cost(self):
		"""Fetch RM rate as per today's valuation rate and calculate totals"""
		total_rm_cost = 0
		for d in self.get('items'):
			if d.bom_no:
				d.rate = self.get_bom_unitcost(d.bom_no)
			d.amount = flt(d.rate, self.precision("rate", d)) * flt(d.qty, self.precision("qty", d))
			d.qty_consumed_per_unit = flt(d.qty, self.precision("qty", d)) / flt(self.quantity, self.precision("quantity"))
			total_rm_cost += d.amount

		self.raw_material_cost = total_rm_cost

	def update_exploded_items(self):
		""" Update Flat BOM, following will be correct data"""
		self.get_exploded_items()
		self.add_exploded_items()

	def get_exploded_items(self):
		""" Get all raw materials including items from child bom"""
		self.cur_exploded_items = {}
		for d in self.get('items'):
			if d.bom_no:
				self.get_child_exploded_items(d.bom_no, d.qty)
			else:
				self.add_to_cur_exploded_items(frappe._dict({
					'item_code'		: d.item_code,
					'item_name'		: d.item_name,
					'description'	: d.description,
					'image'			: d.image,
					'stock_uom'		: d.stock_uom,
					'qty'			: flt(d.qty),
					'rate'			: flt(d.rate),
				}))

	def add_to_cur_exploded_items(self, args):
		if self.cur_exploded_items.get(args.item_code):
			self.cur_exploded_items[args.item_code]["qty"] += args.qty
		else:
			self.cur_exploded_items[args.item_code] = args

	def get_child_exploded_items(self, bom_no, qty):
		""" Add all items from Flat BOM of child BOM"""
		# Did not use qty_consumed_per_unit in the query, as it leads to rounding loss
		child_fb_items = frappe.db.sql("""select bom_item.item_code, bom_item.item_name, bom_item.description,
			bom_item.stock_uom, bom_item.qty, bom_item.rate,
			bom_item.qty / ifnull(bom.quantity, 1) as qty_consumed_per_unit
			from `tabBOM Explosion Item` bom_item, tabBOM bom
			where bom_item.parent = bom.name and bom.name = %s and bom.docstatus = 1""", bom_no, as_dict = 1)

		for d in child_fb_items:
			self.add_to_cur_exploded_items(frappe._dict({
				'item_code'				: d['item_code'],
				'item_name'				: d['item_name'],
				'description'			: d['description'],
				'stock_uom'				: d['stock_uom'],
				'qty'					: d['qty_consumed_per_unit']*qty,
				'rate'					: flt(d['rate']),
			}))

	def add_exploded_items(self):
		"Add items to Flat BOM table"
		frappe.db.sql("""delete from `tabBOM Explosion Item` where parent=%s""", self.name)
		self.set('exploded_items', [])
		for d in sorted(self.cur_exploded_items, key=itemgetter(0)):
			ch = self.append('exploded_items', {})
			for i in self.cur_exploded_items[d].keys():
				ch.set(i, self.cur_exploded_items[d][i])
			ch.amount = flt(ch.qty) * flt(ch.rate)
			ch.qty_consumed_per_unit = flt(ch.qty) / flt(self.quantity)
			ch.docstatus = self.docstatus
			ch.db_insert()

	def validate_bom_links(self):
		if not self.is_active:
			act_pbom = frappe.db.sql("""select distinct bom_item.parent from `tabBOM Item` bom_item
				where bom_item.bom_no = %s and bom_item.docstatus = 1
				and exists (select * from `tabBOM` where name = bom_item.parent
					and docstatus = 1 and is_active = 1)""", self.name)

			if act_pbom and act_pbom[0][0]:
				frappe.throw(_("Cannot deactivate or cancel BOM as it is linked with other BOMs"))

	def validate_operations(self):
		if self.with_operations and not self.get('operations'):
			frappe.throw(_("Operations cannot be left blank."))

def get_bom_items_as_dict(bom, company, qty=1, fetch_exploded=1):
	item_dict = {}

	# Did not use qty_consumed_per_unit in the query, as it leads to rounding loss
	query = """select
				bom_item.item_code,
				item.item_name,
				sum(bom_item.qty/ifnull(bom.quantity, 1)) * %(qty)s as qty,
				item.description,
				item.image,
				item.stock_uom,
				item.default_warehouse,
				item.expense_account as expense_account,
				item.buying_cost_center as cost_center
			from
				`tab{table}` bom_item, `tabBOM` bom, `tabItem` item
			where
				bom_item.parent = bom.name
				and bom_item.docstatus < 2
				and bom_item.parent = %(bom)s
				and item.name = bom_item.item_code
				and is_stock_item = 1
				{conditions}
				group by item_code, stock_uom"""

	if fetch_exploded:
		query = query.format(table="BOM Explosion Item",
			conditions="""and item.is_sub_contracted_item = 0""")
		items = frappe.db.sql(query, { "qty": qty,	"bom": bom }, as_dict=True)
	else:
		query = query.format(table="BOM Item", conditions="")
		items = frappe.db.sql(query, { "qty": qty, "bom": bom }, as_dict=True)

	# make unique
	for item in items:
		if item_dict.has_key(item.item_code):
			item_dict[item.item_code]["qty"] += flt(item.qty)
		else:
			item_dict[item.item_code] = item

	for item, item_details in item_dict.items():
		for d in [["Account", "expense_account", "default_expense_account"],
			["Cost Center", "cost_center", "cost_center"], ["Warehouse", "default_warehouse", ""]]:
				company_in_record = frappe.db.get_value(d[0], item_details.get(d[1]), "company")
				if not item_details.get(d[1]) or (company_in_record and company != company_in_record):
					item_dict[item][d[1]] = frappe.db.get_value("Company", company, d[2]) if d[2] else None

	return item_dict

@frappe.whitelist()
def get_bom_items(bom, company, qty=1, fetch_exploded=1):
	items = get_bom_items_as_dict(bom, company, qty, fetch_exploded).values()
	items.sort(lambda a, b: a.item_code > b.item_code and 1 or -1)
	return items

def validate_bom_no(item, bom_no):
	"""Validate BOM No of sub-contracted items"""
	bom = frappe.get_doc("BOM", bom_no)
	if not bom.is_active:
		frappe.throw(_("BOM {0} must be active").format(bom_no))
	if bom.docstatus != 1:
		if not getattr(frappe.flags, "in_test", False):
			frappe.throw(_("BOM {0} must be submitted").format(bom_no))
	if item and not (bom.item.lower() == item.lower() or \
		bom.item.lower() == cstr(frappe.db.get_value("Item", item, "variant_of")).lower()):
		frappe.throw(_("BOM {0} does not belong to Item {1}").format(bom_no, item))
