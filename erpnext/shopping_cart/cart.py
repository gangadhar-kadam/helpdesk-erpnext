# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import throw, _
import frappe.defaults
from frappe.utils import cint, flt, get_fullname, cstr
from erpnext.utilities.doctype.address.address import get_address_display
from erpnext.shopping_cart.doctype.shopping_cart_settings.shopping_cart_settings import get_shopping_cart_settings
from frappe.utils.nestedset import get_root_of

class WebsitePriceListMissingError(frappe.ValidationError): pass

def set_cart_count(quotation=None):
	if cint(frappe.db.get_singles_value("Shopping Cart Settings", "enabled")):
		if not quotation:
			quotation = _get_cart_quotation()
		cart_count = cstr(len(quotation.get("items")))

		if hasattr(frappe.local, "cookie_manager"):
			frappe.local.cookie_manager.set_cookie("cart_count", cart_count)

@frappe.whitelist()
def get_cart_quotation(doc=None):
	party = get_customer()

	if not doc:
		quotation = _get_cart_quotation(party)
		doc = quotation
		set_cart_count(quotation)

	return {
		"doc": decorate_quotation_doc(doc),
		"addresses": [{"name": address.name, "display": address.display}
			for address in get_address_docs(party=party)],
		"shipping_rules": get_applicable_shipping_rules(party)
	}

@frappe.whitelist()
def place_order():
	quotation = _get_cart_quotation()
	quotation.company = frappe.db.get_value("Shopping Cart Settings", None, "company")
	for fieldname in ["customer_address", "shipping_address_name"]:
		if not quotation.get(fieldname):
			throw(_("{0} is required").format(quotation.meta.get_label(fieldname)))

	quotation.flags.ignore_permissions = True
	quotation.submit()

	if quotation.lead:
		# company used to create customer accounts
		frappe.defaults.set_user_default("company", quotation.company)

	from erpnext.selling.doctype.quotation.quotation import _make_sales_order
	sales_order = frappe.get_doc(_make_sales_order(quotation.name, ignore_permissions=True))
	for item in sales_order.get("items"):
		item.reserved_warehouse = frappe.db.get_value("Item", item.item_code, "website_warehouse") or None

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	sales_order.submit()

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name

@frappe.whitelist()
def update_cart(item_code, qty, with_items=False):
	quotation = _get_cart_quotation()

	qty = flt(qty)
	if qty == 0:
		quotation.set("items", quotation.get("items", {"item_code": ["!=", item_code]}))
	else:
		quotation_items = quotation.get("items", {"item_code": item_code})
		if not quotation_items:
			quotation.append("items", {
				"doctype": "Quotation Item",
				"item_code": item_code,
				"qty": qty
			})
		else:
			quotation_items[0].qty = qty

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	set_cart_count(quotation)

	if with_items:
		context = get_cart_quotation(quotation)
		return {
			"items": frappe.render_template("templates/includes/cart/cart_items.html",
				context),
			"taxes": frappe.render_template("templates/includes/order/order_taxes.html",
				context),
		}
	else:
		return quotation.name

@frappe.whitelist()
def update_cart_address(address_fieldname, address_name):
	quotation = _get_cart_quotation()
	address_display = get_address_display(frappe.get_doc("Address", address_name).as_dict())

	if address_fieldname == "shipping_address_name":
		quotation.shipping_address_name = address_name
		quotation.shipping_address = address_display

		if not quotation.customer_address:
			address_fieldname == "customer_address"

	if address_fieldname == "customer_address":
		quotation.customer_address = address_name
		quotation.address_display = address_display


	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	context = get_cart_quotation(quotation)
	return {
		"taxes": frappe.render_template("templates/includes/order/order_taxes.html",
			context),
		}

def guess_territory():
	territory = None
	geoip_country = frappe.session.get("session_country")
	if geoip_country:
		territory = frappe.db.get_value("Territory", geoip_country)

	return territory or \
		frappe.db.get_value("Shopping Cart Settings", None, "territory") or \
			get_root_of("Territory")

def decorate_quotation_doc(doc):
	for d in doc.get("items", []):
		d.update(frappe.db.get_value("Item", d.item_code,
			["thumbnail", "website_image", "description", "page_name"], as_dict=True))

	return doc

def _get_cart_quotation(party=None):
	if not party:
		party = get_customer()

	quotation = frappe.get_all("Quotation", fields=["name"], filters=
		{party.doctype.lower(): party.name, "order_type": "Shopping Cart", "docstatus": 0},
		order_by="modified desc", limit_page_length=1)

	if quotation:
		qdoc = frappe.get_doc("Quotation", quotation[0].name)
	else:
		qdoc = frappe.get_doc({
			"doctype": "Quotation",
			"naming_series": get_shopping_cart_settings().quotation_series or "QTN-CART-",
			"quotation_to": party.doctype,
			"company": frappe.db.get_value("Shopping Cart Settings", None, "company"),
			"order_type": "Shopping Cart",
			"status": "Draft",
			"docstatus": 0,
			"__islocal": 1,
			(party.doctype.lower()): party.name
		})

		qdoc.contact_person = frappe.db.get_value("Contact", {"email_id": frappe.session.user,
			"customer": party.name})
		qdoc.contact_email = frappe.session.user

		qdoc.flags.ignore_permissions = True
		qdoc.run_method("set_missing_values")
		apply_cart_settings(party, qdoc)

	return qdoc

def update_party(fullname, company_name=None, mobile_no=None, phone=None):
	party = get_customer()

	party.customer_name = company_name or fullname
	party.customer_type == "Company" if company_name else "Individual"

	contact_name = frappe.db.get_value("Contact", {"email_id": frappe.session.user,
		"customer": party.name})
	contact = frappe.get_doc("Contact", contact_name)
	contact.first_name = fullname
	contact.last_name = None
	contact.customer_name = party.customer_name
	contact.mobile_no = mobile_no
	contact.phone = phone
	contact.flags.ignore_permissions = True
	contact.save()

	party_doc = frappe.get_doc(party.as_dict())
	party_doc.flags.ignore_permissions = True
	party_doc.save()

	qdoc = _get_cart_quotation(party)
	if not qdoc.get("__islocal"):
		qdoc.customer_name = company_name or fullname
		qdoc.run_method("set_missing_lead_customer_details")
		qdoc.flags.ignore_permissions = True
		qdoc.save()

def apply_cart_settings(party=None, quotation=None):
	if not party:
		party = get_customer()
	if not quotation:
		quotation = _get_cart_quotation(party)

	cart_settings = frappe.get_doc("Shopping Cart Settings")

	set_price_list_and_rate(quotation, cart_settings)

	quotation.run_method("calculate_taxes_and_totals")

	set_taxes(quotation, cart_settings)

	_apply_shipping_rule(party, quotation, cart_settings)

def set_price_list_and_rate(quotation, cart_settings):
	"""set price list based on billing territory"""

	_set_price_list(quotation, cart_settings)

	# reset values
	quotation.price_list_currency = quotation.currency = \
		quotation.plc_conversion_rate = quotation.conversion_rate = None
	for item in quotation.get("items"):
		item.price_list_rate = item.discount_percentage = item.rate = item.amount = None

	# refetch values
	quotation.run_method("set_price_list_and_item_details")

	if hasattr(frappe.local, "cookie_manager"):
		# set it in cookies for using in product page
		frappe.local.cookie_manager.set_cookie("selling_price_list", quotation.selling_price_list)

def _set_price_list(quotation, cart_settings):
	"""Set price list based on customer or shopping cart default"""
	if quotation.selling_price_list:
		return

	# check if customer price list exists
	selling_price_list = None
	if quotation.customer:
		from erpnext.accounts.party import get_default_price_list
		selling_price_list = get_default_price_list(frappe.get_doc("Customer", quotation.customer))

	# else check for territory based price list
	if not selling_price_list:
		selling_price_list = cart_settings.price_list

	quotation.selling_price_list = selling_price_list

def set_taxes(quotation, cart_settings):
	"""set taxes based on billing territory"""
	from erpnext.accounts.party import set_taxes

	customer_group = frappe.db.get_value("Customer", quotation.customer, "customer_group")

	quotation.taxes_and_charges = set_taxes(quotation.customer, "Customer", \
		quotation.transaction_date, quotation.company, customer_group, None, \
		quotation.customer_address, quotation.shipping_address_name, 1)
#
# 	# clear table
	quotation.set("taxes", [])
#
# 	# append taxes
	quotation.append_taxes_from_master()

def get_customer(user=None):
	if not user:
		user = frappe.session.user

	customer = frappe.db.get_value("Contact", {"email_id": user}, "customer")

	if customer:
		return frappe.get_doc("Customer", customer)

	else:
		customer = frappe.new_doc("Customer")
		fullname = get_fullname(user)
		customer.update({
			"customer_name": fullname,
			"customer_type": "Individual",
			"customer_group": get_shopping_cart_settings().default_customer_group,
			"territory": get_root_of("Territory")
		})
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

		contact = frappe.new_doc("Contact")
		contact.update({
			"customer": customer.name,
			"first_name": fullname,
			"email_id": user
		})
		contact.flags.ignore_mandatory = True
		contact.insert(ignore_permissions=True)

		return customer

def get_address_docs(doctype=None, txt=None, filters=None, limit_start=0, limit_page_length=20, party=None):
	if not party:
		party = get_customer()

	address_docs = frappe.db.sql("""select * from `tabAddress`
		where `{0}`=%s order by name limit {1}, {2}""".format(party.doctype.lower(),
			limit_start, limit_page_length), party.name,
		as_dict=True, update={"doctype": "Address"})

	for address in address_docs:
		address.display = get_address_display(address)

	return address_docs

def set_customer_in_address(doc, method=None):
	if doc.flags.linked:
		return

	doc.check_if_linked()

	if not doc.flags.linked and (frappe.db.get_value("User", frappe.session.user, "user_type") == "Website User"):
		# creates a customer if one does not exist
		get_customer()
		doc.link_address()

@frappe.whitelist()
def apply_shipping_rule(shipping_rule):
	quotation = _get_cart_quotation()

	quotation.shipping_rule = shipping_rule

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	return get_cart_quotation(quotation)

def _apply_shipping_rule(party=None, quotation=None, cart_settings=None):
	if not quotation.shipping_rule:
		shipping_rules = get_shipping_rules(quotation, cart_settings)

		if not shipping_rules:
			return

		elif quotation.shipping_rule not in shipping_rules:
			quotation.shipping_rule = shipping_rules[0]

	if quotation.shipping_rule:
		quotation.run_method("apply_shipping_rule")
		quotation.run_method("calculate_taxes_and_totals")

def get_applicable_shipping_rules(party=None, quotation=None):
	shipping_rules = get_shipping_rules(quotation)

	if shipping_rules:
		rule_label_map = frappe.db.get_values("Shipping Rule", shipping_rules, "label")
		# we need this in sorted order as per the position of the rule in the settings page
		return [[rule, rule_label_map.get(rule)] for rule in shipping_rules]

def get_shipping_rules(quotation=None, cart_settings=None):
	if not quotation:
		quotation = _get_cart_quotation()

	shipping_rules = []
	if quotation.shipping_address_name:
		country = frappe.db.get_value("Address", quotation.shipping_address_name, "country")
		if country:
			shipping_rules = frappe.db.sql_list("""select distinct sr.name
				from `tabShipping Rule Country` src, `tabShipping Rule` sr
				where src.country = %s and
				sr.disabled != 1 and sr.name = src.parent""", country)

	return shipping_rules

def get_address_territory(address_name):
	"""Tries to match city, state and country of address to existing territory"""
	territory = None

	if address_name:
		address_fields = frappe.db.get_value("Address", address_name,
			["city", "state", "country"])
		for value in address_fields:
			territory = frappe.db.get_value("Territory", value)
			if territory:
				break

	return territory
