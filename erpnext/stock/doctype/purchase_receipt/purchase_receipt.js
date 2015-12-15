// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

{% include 'buying/doctype/purchase_common/purchase_common.js' %};

frappe.provide("erpnext.stock");

frappe.ui.form.on("Purchase Receipt", {
	onload: function(frm) {
		// default values for quotation no
		var qa_no = frappe.meta.get_docfield("Purchase Receipt Item", "qa_no");
		qa_no.get_route_options_for_new_doc = function(field) {
			if(frm.is_new()) return;
			var doc = field.doc;
			return {
				"inspection_type": "Incoming",
				"purchase_receipt_no": frm.doc.name,
				"item_code": doc.item_code,
				"description": doc.description,
				"item_serial_no": doc.serial_no ? doc.serial_no.split("\n")[0] : null,
				"batch_no": doc.batch_no
			}
		}
	}
});


erpnext.stock.PurchaseReceiptController = erpnext.buying.BuyingController.extend({
	refresh: function() {
		this._super();

		if(this.frm.doc.docstatus===1) {
			this.show_stock_ledger();
			if (cint(frappe.defaults.get_default("auto_accounting_for_stock"))) {
				this.show_general_ledger();
			}
		}

		if(!this.frm.doc.is_return && this.frm.doc.status!="Closed") {
			if(this.frm.doc.docstatus==0) {
				cur_frm.add_custom_button(__('From Purchase Order'),
					function() {
						frappe.model.map_current_doc({
							method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
							source_doctype: "Purchase Order",
							get_query_filters: {
								supplier: cur_frm.doc.supplier || undefined,
								docstatus: 1,
								status: ["not in", ["Stopped", "Closed"]],
								per_received: ["<", 99.99],
								company: cur_frm.doc.company
							}
						})
				});
			}

			if(this.frm.doc.docstatus == 1 && this.frm.doc.status!="Closed") {
				cur_frm.add_custom_button(__('Return'), this.make_purchase_return);
				if(this.frm.doc.__onload && !this.frm.doc.__onload.billing_complete) {
					cur_frm.add_custom_button(__('Invoice'),
						 this.make_purchase_invoice).addClass("btn-primary");
				}
				if (this.frm.has_perm("submit") && 
					this.frm.doc.__onload && this.frm.doc.__onload.has_return_entry) {
						cur_frm.add_custom_button(__("Close"), this.close_purchase_receipt)
				}
			}
		}


		if(this.frm.doc.docstatus==1 && this.frm.doc.status === "Closed" && this.frm.has_perm("submit")) {
			cur_frm.add_custom_button(__('Re-open'), this.reopen_purchase_receipt)
		}

		this.frm.toggle_reqd("supplier_warehouse", this.frm.doc.is_subcontracted==="Yes");
	},

	received_qty: function(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["qty", "received_qty"]);

		item.qty = (item.qty < item.received_qty) ? item.qty : item.received_qty;
		this.qty(doc, cdt, cdn);
	},

	qty: function(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["qty", "received_qty"]);

		if(!(item.received_qty || item.rejected_qty) && item.qty) {
			item.received_qty = item.qty;
		}

		if(item.qty > item.received_qty) {
			msgprint(__("Error: {0} > {1}", [__(frappe.meta.get_label(item.doctype, "qty", item.name)),
						__(frappe.meta.get_label(item.doctype, "received_qty", item.name))]))
			item.qty = item.rejected_qty = 0.0;
		} else {
			item.rejected_qty = flt(item.received_qty - item.qty, precision("rejected_qty", item));
		}

		this._super(doc, cdt, cdn);
	},

	rejected_qty: function(doc, cdt, cdn) {
		var item = frappe.get_doc(cdt, cdn);
		frappe.model.round_floats_in(item, ["received_qty", "rejected_qty"]);

		if(item.rejected_qty > item.received_qty) {
			msgprint(__("Error: {0} > {1}", [__(frappe.meta.get_label(item.doctype, "rejected_qty", item.name)),
						__(frappe.meta.get_label(item.doctype, "received_qty", item.name))]));
			item.qty = item.rejected_qty = 0.0;
		} else {
			item.qty = flt(item.received_qty - item.rejected_qty, precision("qty", item));
		}

		this.qty(doc, cdt, cdn);
	},

	make_purchase_invoice: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice",
			frm: cur_frm
		})
	},

	make_purchase_return: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
			frm: cur_frm
		})
	},

	tc_name: function() {
		this.get_terms();
	},

	close_purchase_receipt: function() {
		cur_frm.cscript.update_status("Closed");
	},

	reopen_purchase_receipt: function() {
		cur_frm.cscript.update_status("Submitted");
	}

});

// for backward compatibility: combine new and previous states
$.extend(cur_frm.cscript, new erpnext.stock.PurchaseReceiptController({frm: cur_frm}));

cur_frm.cscript.update_status = function(status) {
	frappe.ui.form.is_saving = true;
	frappe.call({
		method:"erpnext.stock.doctype.purchase_receipt.purchase_receipt.update_purchase_receipt_status",
		args: {docname: cur_frm.doc.name, status: status},
		callback: function(r){
			if(!r.exc)
				cur_frm.reload_doc();
		},
		always: function(){
			frappe.ui.form.is_saving = false;
		}
	})
}

cur_frm.fields_dict['supplier_address'].get_query = function(doc, cdt, cdn) {
	return {
		filters: { 'supplier': doc.supplier}
	}
}

cur_frm.fields_dict['contact_person'].get_query = function(doc, cdt, cdn) {
	return {
		filters: { 'supplier': doc.supplier }
	}
}

cur_frm.cscript.new_contact = function() {
	tn = frappe.model.make_new_doc_and_get_name('Contact');
	locals['Contact'][tn].is_supplier = 1;
	if(doc.supplier)
		locals['Contact'][tn].supplier = doc.supplier;
	loaddoc('Contact', tn);
}

cur_frm.fields_dict['items'].grid.get_field('project_name').get_query = function(doc, cdt, cdn) {
	return {
		filters: [
			['Project', 'status', 'not in', 'Completed, Cancelled']
		]
	}
}

cur_frm.fields_dict['items'].grid.get_field('batch_no').get_query= function(doc, cdt, cdn) {
	var d = locals[cdt][cdn];
	if(d.item_code) {
		return {
			filters: {'item': d.item_code}
		}
	}
	else
		msgprint(__("Please enter Item Code."));
}

cur_frm.cscript.select_print_heading = function(doc, cdt, cdn) {
	if(doc.select_print_heading)
		cur_frm.pformat.print_heading = doc.select_print_heading;
	else
		cur_frm.pformat.print_heading = "Purchase Receipt";
}

cur_frm.fields_dict['select_print_heading'].get_query = function(doc, cdt, cdn) {
	return {
		filters: [
			['Print Heading', 'docstatus', '!=', '2']
		]
	}
}

cur_frm.fields_dict.items.grid.get_field("qa_no").get_query = function(doc) {
	return {
		filters: {
			'docstatus': 1
		}
	}
}

cur_frm.fields_dict['items'].grid.get_field('bom').get_query = function(doc, cdt, cdn) {
	var d = locals[cdt][cdn]
	return {
		filters: [
			['BOM', 'item', '=', d.item_code],
			['BOM', 'is_active', '=', '1'],
			['BOM', 'docstatus', '=', '1']
		]
	}
}

cur_frm.cscript.on_submit = function(doc, cdt, cdn) {
	if(cint(frappe.boot.notification_settings.purchase_receipt))
		cur_frm.email_doc(frappe.boot.notification_settings.purchase_receipt_message);
}



frappe.provide("erpnext.buying");

frappe.ui.form.on("Purchase Receipt", "is_subcontracted", function(frm) {
	if (frm.doc.is_subcontracted === "Yes") {
		erpnext.buying.get_default_bom(frm);
	}
	frm.toggle_reqd("supplier_warehouse", frm.doc.is_subcontracted==="Yes");
});
