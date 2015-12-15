# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import _, throw
from frappe.utils import flt, cint, add_days, cstr
import json
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item
from erpnext.setup.utils import get_exchange_rate
from frappe.model.meta import get_field_precision

@frappe.whitelist()
def get_item_details(args):
	"""
		args = {
			"item_code": "",
			"warehouse": None,
			"customer": "",
			"conversion_rate": 1.0,
			"selling_price_list": None,
			"price_list_currency": None,
			"plc_conversion_rate": 1.0,
			"parenttype": "",
			"parent": "",
			"supplier": None,
			"transaction_date": None,
			"conversion_rate": 1.0,
			"buying_price_list": None,
			"is_subcontracted": "Yes" / "No",
			"transaction_type": "selling",
			"ignore_pricing_rule": 0/1
			"project_name": ""
		}
	"""
	args = process_args(args)
	item_doc = frappe.get_doc("Item", args.item_code)
	item = item_doc

	validate_item_details(args, item)

	out = get_basic_details(args, item)

	get_party_item_code(args, item_doc, out)

	if out.get("warehouse"):
		out.update(get_available_qty(args.item_code, out.warehouse))
		out.update(get_projected_qty(item.name, out.warehouse))

	get_price_list_rate(args, item_doc, out)

	if args.transaction_type == "selling" and cint(args.is_pos):
		out.update(get_pos_profile_item_details(args.company, args))

	# update args with out, if key or value not exists
	for key, value in out.iteritems():
		if args.get(key) is None:
			args[key] = value

	out.update(get_pricing_rule_for_item(args))

	if args.get("parenttype") in ("Sales Invoice", "Delivery Note"):
		if item_doc.has_serial_no == 1 and not args.serial_no:
			out.serial_no = get_serial_nos_by_fifo(args, item_doc)

	if args.transaction_date and item.lead_time_days:
		out.schedule_date = out.lead_time_date = add_days(args.transaction_date,
			item.lead_time_days)

	if args.get("is_subcontracted") == "Yes":
		out.bom = get_default_bom(args.item_code)

	return out

def process_args(args):
	if isinstance(args, basestring):
		args = json.loads(args)

	args = frappe._dict(args)

	if not args.get("transaction_type"):
		if args.get("parenttype")=="Material Request" or \
				frappe.get_meta(args.get("parenttype")).get_field("supplier"):
			args.transaction_type = "buying"
		else:
			args.transaction_type = "selling"

	if not args.get("price_list"):
		args.price_list = args.get("selling_price_list") or args.get("buying_price_list")

	if args.barcode:
		args.item_code = get_item_code(barcode=args.barcode)
	elif not args.item_code and args.serial_no:
		args.item_code = get_item_code(serial_no=args.serial_no)

	return args

@frappe.whitelist()
def get_item_code(barcode=None, serial_no=None):
	if barcode:
		item_code = frappe.db.get_value("Item", {"barcode": barcode})
		if not item_code:
			frappe.throw(_("No Item with Barcode {0}").format(barcode))
	elif serial_no:
		item_code = frappe.db.get_value("Serial No", serial_no, "item_code")
		if not item_code:
			frappe.throw(_("No Item with Serial No {0}").format(serial_no))

	return item_code

def validate_item_details(args, item):
	if not args.company:
		throw(_("Please specify Company"))

	from erpnext.stock.doctype.item.item import validate_end_of_life
	validate_end_of_life(item.name, item.end_of_life, item.disabled)

	if args.transaction_type == "selling":
		# validate if sales item or service item
		if args.get("order_type") == "Maintenance":
			if item.is_service_item != 1:
				throw(_("Item {0} must be a Service Item.").format(item.name))

		elif item.is_sales_item != 1:
			throw(_("Item {0} must be a Sales Item").format(item.name))

		if cint(item.has_variants):
			throw(_("Item {0} is a template, please select one of its variants").format(item.name))

	elif args.transaction_type == "buying" and args.parenttype != "Material Request":
		# validate if purchase item or subcontracted item
		if item.is_purchase_item != 1:
			throw(_("Item {0} must be a Purchase Item").format(item.name))

		if args.get("is_subcontracted") == "Yes" and item.is_sub_contracted_item != 1:
			throw(_("Item {0} must be a Sub-contracted Item").format(item.name))

def get_basic_details(args, item):
	if not item:
		item = frappe.get_doc("Item", args.get("item_code"))

	if item.variant_of:
		item.update_template_tables()

	from frappe.defaults import get_user_default_as_list
	user_default_warehouse_list = get_user_default_as_list('warehouse')
	user_default_warehouse = user_default_warehouse_list[0] \
		if len(user_default_warehouse_list)==1 else ""

	out = frappe._dict({
		"item_code": item.name,
		"item_name": item.item_name,
		"description": cstr(item.description).strip(),
		"image": cstr(item.image).strip(),
		"warehouse": user_default_warehouse or args.warehouse or item.default_warehouse,
		"income_account": get_default_income_account(args, item),
		"expense_account": get_default_expense_account(args, item),
		"cost_center": get_default_cost_center(args, item),
		"batch_no": None,
		"item_tax_rate": json.dumps(dict(([d.tax_type, d.tax_rate] for d in
			item.get("taxes")))),
		"uom": item.stock_uom,
		"min_order_qty": flt(item.min_order_qty) if args.parenttype == "Material Request" else "",
		"conversion_factor": 1.0,
		"qty": args.qty or 1.0,
		"stock_qty": 1.0,
		"price_list_rate": 0.0,
		"base_price_list_rate": 0.0,
		"rate": 0.0,
		"base_rate": 0.0,
		"amount": 0.0,
		"base_amount": 0.0,
		"net_rate": 0.0,
		"net_amount": 0.0,
		"discount_percentage": 0.0,
		"supplier": item.default_supplier,
		"delivered_by_supplier": item.delivered_by_supplier,
	})

	# if default specified in item is for another company, fetch from company
	for d in [["Account", "income_account", "default_income_account"], ["Account", "expense_account", "default_expense_account"],
		["Cost Center", "cost_center", "cost_center"], ["Warehouse", "warehouse", ""]]:
			company = frappe.db.get_value(d[0], out.get(d[1]), "company")
			if not out[d[1]] or (company and args.company != company):
				out[d[1]] = frappe.db.get_value("Company", args.company, d[2]) if d[2] else None

	for fieldname in ("item_name", "item_group", "barcode", "brand", "stock_uom"):
		out[fieldname] = item.get(fieldname)

	return out

def get_default_income_account(args, item):
	return (item.income_account
		or args.income_account
		or frappe.db.get_value("Item Group", item.item_group, "default_income_account"))

def get_default_expense_account(args, item):
	return (item.expense_account
		or args.expense_account
		or frappe.db.get_value("Item Group", item.item_group, "default_expense_account"))

def get_default_cost_center(args, item):
	return (frappe.db.get_value("Project", args.get("project_name"), "cost_center")
		or (item.selling_cost_center if args.get("transaction_type") == "selling" else item.buying_cost_center)
		or frappe.db.get_value("Item Group", item.item_group, "default_cost_center")
		or args.get("cost_center"))

def get_price_list_rate(args, item_doc, out):
	meta = frappe.get_meta(args.parenttype)

	if meta.get_field("currency"):
		validate_price_list(args)
		validate_conversion_rate(args, meta)

		price_list_rate = get_price_list_rate_for(args, item_doc.name)
		if not price_list_rate and item_doc.variant_of:
			price_list_rate = get_price_list_rate_for(args, item_doc.variant_of)

		if not price_list_rate:
			if args.price_list and args.rate:
				insert_item_price(args)
			return {}

		out.price_list_rate = flt(price_list_rate) * flt(args.plc_conversion_rate) \
			/ flt(args.conversion_rate)

		if not out.price_list_rate and args.transaction_type == "buying":
			from erpnext.stock.doctype.item.item import get_last_purchase_details
			out.update(get_last_purchase_details(item_doc.name,
				args.parent, args.conversion_rate))

def insert_item_price(args):
	"""Insert Item Price if Price List and Price List Rate are specified and currency is the same"""
	if frappe.db.get_value("Price List", args.price_list, "currency") == args.currency \
		and cint(frappe.db.get_single_value("Stock Settings", "auto_insert_price_list_rate_if_missing")):
		if frappe.has_permission("Item Price", "write"):

			price_list_rate = args.rate / args.conversion_factor \
				if args.get("conversion_factor") else args.rate

			item_price = frappe.get_doc({
				"doctype": "Item Price",
				"price_list": args.price_list,
				"item_code": args.item_code,
				"currency": args.currency,
				"price_list_rate": price_list_rate
			})
			item_price.insert()
			frappe.msgprint("Item Price added for {0} in Price List {1}".format(args.item_code,
				args.price_list))

def get_price_list_rate_for(args, item_code):
	return frappe.db.get_value("Item Price",
			{"price_list": args.price_list, "item_code": item_code}, "price_list_rate")

def validate_price_list(args):
	if args.get("price_list"):
		if not frappe.db.get_value("Price List",
			{"name": args.price_list, args.transaction_type: 1, "enabled": 1}):
			throw(_("Price List {0} is disabled").format(args.price_list))
	else:
		throw(_("Price List not selected"))

def validate_conversion_rate(args, meta):
	from erpnext.controllers.accounts_controller import validate_conversion_rate

	if (not args.conversion_rate
		and args.currency==frappe.db.get_value("Company", args.company, "default_currency")):
		args.conversion_rate = 1.0

	# validate currency conversion rate
	validate_conversion_rate(args.currency, args.conversion_rate,
		meta.get_label("conversion_rate"), args.company)

	args.conversion_rate = flt(args.conversion_rate,
		get_field_precision(meta.get_field("conversion_rate"),
			frappe._dict({"fields": args})))

	# validate price list currency conversion rate
	if not args.get("price_list_currency"):
		throw(_("Price List Currency not selected"))
	else:
		validate_conversion_rate(args.price_list_currency, args.plc_conversion_rate,
			meta.get_label("plc_conversion_rate"), args.company)

		args.plc_conversion_rate = flt(args.plc_conversion_rate,
			get_field_precision(meta.get_field("plc_conversion_rate"),
			frappe._dict({"fields": args})))

def get_party_item_code(args, item_doc, out):
	if args.transaction_type == "selling":
		customer_item_code = item_doc.get("customer_items", {"customer_name": args.customer})
		out.customer_item_code = customer_item_code[0].ref_code if customer_item_code else None
	else:
		item_supplier = item_doc.get("supplier_items", {"supplier": args.supplier})
		out.supplier_part_no = item_supplier[0].supplier_part_no if item_supplier else None

def get_pos_profile_item_details(company, args, pos_profile=None):
	res = frappe._dict()

	if not pos_profile:
		pos_profile = get_pos_profile(company)

	if pos_profile:
		for fieldname in ("income_account", "cost_center", "warehouse", "expense_account"):
			if not args.get(fieldname) and pos_profile.get(fieldname):
				res[fieldname] = pos_profile.get(fieldname)

		if res.get("warehouse"):
			res.actual_qty = get_available_qty(args.item_code,
				res.warehouse).get("actual_qty")

	return res

@frappe.whitelist()
def get_pos_profile(company):
	pos_profile = frappe.db.sql("""select * from `tabPOS Profile` where user = %s
		and company = %s""", (frappe.session['user'], company), as_dict=1)

	if not pos_profile:
		pos_profile = frappe.db.sql("""select * from `tabPOS Profile`
			where ifnull(user,'') = '' and company = %s""", company, as_dict=1)

	return pos_profile and pos_profile[0] or None


def get_serial_nos_by_fifo(args, item_doc):
	if frappe.db.get_single_value("Stock Settings", "automatically_set_serial_nos_based_on_fifo"):
		return "\n".join(frappe.db.sql_list("""select name from `tabSerial No`
			where item_code=%(item_code)s and warehouse=%(warehouse)s
			order by timestamp(purchase_date, purchase_time) asc limit %(qty)s""", {
				"item_code": args.item_code,
				"warehouse": args.warehouse,
				"qty": abs(cint(args.qty))
			}))

def get_actual_batch_qty(batch_no,warehouse,item_code):
	actual_batch_qty = 0
	if batch_no:
		actual_batch_qty = flt(frappe.db.sql("""select sum(actual_qty)
			from `tabStock Ledger Entry`
			where warehouse=%s and item_code=%s and batch_no=%s""",
			(warehouse, item_code, batch_no))[0][0])
	return actual_batch_qty

@frappe.whitelist()
def get_conversion_factor(item_code, uom):
	variant_of = frappe.db.get_value("Item", item_code, "variant_of")
	filters = {"parent": item_code, "uom": uom}
	if variant_of:
		filters["parent"] = ("in", (item_code, variant_of))
	return {"conversion_factor": frappe.db.get_value("UOM Conversion Detail",
		filters, "conversion_factor")}

@frappe.whitelist()
def get_projected_qty(item_code, warehouse):
	return {"projected_qty": frappe.db.get_value("Bin",
		{"item_code": item_code, "warehouse": warehouse}, "projected_qty")}

@frappe.whitelist()
def get_available_qty(item_code, warehouse):
	return frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse},
		["projected_qty", "actual_qty"], as_dict=True) or {}

@frappe.whitelist()
def get_batch_qty(batch_no,warehouse,item_code):
	actual_batch_qty = get_actual_batch_qty(batch_no,warehouse,item_code)
	if batch_no:
		return {'actual_batch_qty': actual_batch_qty}

@frappe.whitelist()
def apply_price_list(args):
	"""
		args = {
			"item_list": [{"doctype": "", "name": "", "item_code": "", "brand": "", "item_group": ""}, ...],
			"conversion_rate": 1.0,
			"selling_price_list": None,
			"price_list_currency": None,
			"plc_conversion_rate": 1.0,
			"parenttype": "",
			"parent": "",
			"supplier": None,
			"transaction_date": None,
			"conversion_rate": 1.0,
			"buying_price_list": None,
			"transaction_type": "selling",
			"ignore_pricing_rule": 0/1
		}
	"""
	args = process_args(args)

	parent = get_price_list_currency_and_exchange_rate(args)
	children = []

	if "item_list" in args:
		item_list = args.get("item_list")
		del args["item_list"]

		args.update(parent)

		for item in item_list:
			args_copy = frappe._dict(args.copy())
			args_copy.update(item)
			item_details = apply_price_list_on_item(args_copy)
			children.append(item_details)

	return {
		"parent": parent,
		"children": children
	}

def apply_price_list_on_item(args):
	item_details = frappe._dict()
	item_doc = frappe.get_doc("Item", args.item_code)
	get_price_list_rate(args, item_doc, item_details)
	item_details.update(get_pricing_rule_for_item(args))
	return item_details

def get_price_list_currency(price_list):
	if price_list:
		result = frappe.db.get_value("Price List", {"name": price_list,
			"enabled": 1}, ["name", "currency"], as_dict=True)

		if not result:
			throw(_("Price List {0} is disabled").format(price_list))

		return result.currency

def get_price_list_currency_and_exchange_rate(args):
	if not args.price_list:
		return {}

	price_list_currency = get_price_list_currency(args.price_list)
	plc_conversion_rate = args.plc_conversion_rate

	if (not plc_conversion_rate) or (price_list_currency and args.price_list_currency \
		and price_list_currency != args.price_list_currency):
			plc_conversion_rate = get_exchange_rate(price_list_currency, args.currency) or plc_conversion_rate

	return {
		"price_list_currency": price_list_currency,
		"plc_conversion_rate": plc_conversion_rate
	}

@frappe.whitelist()
def get_default_bom(item_code=None):
	if item_code:
		bom = frappe.db.get_value("BOM", {"docstatus": 1, "is_default": 1, "is_active": 1, "item": item_code})
		if bom:
			return bom
		else:
			frappe.throw(_("No default BOM exists for Item {0}").format(item_code))
