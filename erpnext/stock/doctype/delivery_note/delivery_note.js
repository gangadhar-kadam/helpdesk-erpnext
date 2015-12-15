// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

{% include 'selling/sales_common.js' %};

frappe.provide("erpnext.stock");
frappe.provide("erpnext.stock.delivery_note");
erpnext.stock.DeliveryNoteController = erpnext.selling.SellingController.extend({
	refresh: function(doc, dt, dn) {
		this._super();

		if (!doc.is_return && doc.status!="Closed") {
			if(flt(doc.per_installed, 2) < 100 && doc.docstatus==1)
				cur_frm.add_custom_button(__('Installation Note'), this.make_installation_note);

			if (doc.docstatus==1) {
				cur_frm.add_custom_button(__('Sales Return'), this.make_sales_return);
			}

			if(doc.docstatus==0 && !doc.__islocal) {
				cur_frm.add_custom_button(__('Packing Slip'),
					cur_frm.cscript['Make Packing Slip'], frappe.boot.doctype_icons["Packing Slip"]);
			}

			if (this.frm.doc.docstatus===0) {
				cur_frm.add_custom_button(__('From Sales Order'),
					function() {
						frappe.model.map_current_doc({
							method: "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note",
							source_doctype: "Sales Order",
							get_query_filters: {
								docstatus: 1,
								status: ["not in", ["Stopped", "Closed"]],
								per_delivered: ["<", 99.99],
								project_name: cur_frm.doc.project_name || undefined,
								customer: cur_frm.doc.customer || undefined,
								company: cur_frm.doc.company
							}
						})
					});
			}
		}

		if (doc.docstatus==1) {
			this.show_stock_ledger();
			if (cint(frappe.defaults.get_default("auto_accounting_for_stock"))) {
				this.show_general_ledger();
			}
			if (this.frm.has_perm("submit") && (doc.status !== "Closed") 
				&& this.frm.doc.__onload && this.frm.doc.__onload.has_return_entry) {
					cur_frm.add_custom_button(__("Close"), this.close_delivery_note)
			}
		}

		if(doc.__onload && !doc.__onload.billing_complete && doc.docstatus==1 
				&& !doc.is_return && doc.status!="Closed") {
			// show Make Invoice button only if Delivery Note is not created from Sales Invoice
			var from_sales_invoice = false;
			from_sales_invoice = cur_frm.doc.items.some(function(item) {
				return item.against_sales_invoice ? true : false;
			});

			if(!from_sales_invoice)
				cur_frm.add_custom_button(__('Invoice'), this.make_sales_invoice).addClass("btn-primary");
		}

		if(doc.docstatus==1 && doc.status === "Closed" && this.frm.has_perm("submit")) {
			cur_frm.add_custom_button(__('Re-open'), this.reopen_delivery_note)
		}
		erpnext.stock.delivery_note.set_print_hide(doc, dt, dn);

		// unhide expense_account and cost_center is auto_accounting_for_stock enabled
		var aii_enabled = cint(sys_defaults.auto_accounting_for_stock)
		cur_frm.fields_dict["items"].grid.set_column_disp(["expense_account", "cost_center"], aii_enabled);
	},

	make_sales_invoice: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
			frm: cur_frm
		})
	},

	make_installation_note: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_installation_note",
			frm: cur_frm
		});
	},

	make_sales_return: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_return",
			frm: cur_frm
		})
	},

	tc_name: function() {
		this.get_terms();
	},

	items_on_form_rendered: function(doc, grid_row) {
		erpnext.setup_serial_no();
	},

	close_delivery_note: function(doc){
		cur_frm.cscript.update_status("Closed")
	},

	reopen_delivery_note : function() {
		cur_frm.cscript.update_status("Submitted")
	}

});

// for backward compatibility: combine new and previous states
$.extend(cur_frm.cscript, new erpnext.stock.DeliveryNoteController({frm: cur_frm}));

cur_frm.cscript.new_contact = function(){
	tn = frappe.model.make_new_doc_and_get_name('Contact');
	locals['Contact'][tn].is_customer = 1;
	if(doc.customer) locals['Contact'][tn].customer = doc.customer;
	loaddoc('Contact', tn);
}


cur_frm.cscript.update_status = function(status) {
	frappe.ui.form.is_saving = true;
	frappe.call({
		method:"erpnext.stock.doctype.delivery_note.delivery_note.update_delivery_note_status",
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

// ***************** Get project name *****************
cur_frm.fields_dict['project_name'].get_query = function(doc, cdt, cdn) {
	return {
		query: "erpnext.controllers.queries.get_project_name",
		filters: {
			'customer': doc.customer
		}
	}
}

cur_frm.fields_dict['transporter_name'].get_query = function(doc) {
	return{
		filters: { 'supplier_type': "transporter" }
	}
}

cur_frm.cscript['Make Packing Slip'] = function() {
	frappe.model.open_mapped_doc({
		method: "erpnext.stock.doctype.delivery_note.delivery_note.make_packing_slip",
		frm: cur_frm
	})
}

erpnext.stock.delivery_note.set_print_hide = function(doc, cdt, cdn){
	var dn_fields = frappe.meta.docfield_map['Delivery Note'];
	var dn_item_fields = frappe.meta.docfield_map['Delivery Note Item'];
	var dn_fields_copy = dn_fields;
	var dn_item_fields_copy = dn_item_fields;

	if (doc.print_without_amount) {
		dn_fields['currency'].print_hide = 1;
		dn_item_fields['rate'].print_hide = 1;
		dn_item_fields['discount_percentage'].print_hide = 1;
		dn_item_fields['price_list_rate'].print_hide = 1;
		dn_item_fields['amount'].print_hide = 1;
		dn_fields['taxes'].print_hide = 1;
	} else {
		if (dn_fields_copy['currency'].print_hide != 1)
			dn_fields['currency'].print_hide = 0;
		if (dn_item_fields_copy['rate'].print_hide != 1)
			dn_item_fields['rate'].print_hide = 0;
		if (dn_item_fields_copy['amount'].print_hide != 1)
			dn_item_fields['amount'].print_hide = 0;
		if (dn_fields_copy['taxes'].print_hide != 1)
			dn_fields['taxes'].print_hide = 0;
	}
}

cur_frm.cscript.print_without_amount = function(doc, cdt, cdn) {
	erpnext.stock.delivery_note.set_print_hide(doc, cdt, cdn);
}


//****************** For print sales order no and date*************************
cur_frm.pformat.sales_order_no= function(doc, cdt, cdn){
	//function to make row of table

	var make_row = function(title,val1, val2, bold){
		var bstart = '<b>'; var bend = '</b>';

		return '<tr><td style="width:39%;">'+(bold?bstart:'')+title+(bold?bend:'')+'</td>'
		 +'<td style="width:61%;text-align:left;">'+val1+(val2?' ('+dateutil.str_to_user(val2)+')':'')+'</td>'
		 +'</tr>'
	}

	out ='';

	var cl = doc.items || [];

	// outer table
	var out='<div><table class="noborder" style="width:100%"><tr><td style="width: 50%"></td><td>';

	// main table
	out +='<table class="noborder" style="width:100%">';

	// add rows
	if(cl.length){
		prevdoc_list = new Array();
		for(var i=0;i<cl.length;i++){
			if(cl[i].against_sales_order && prevdoc_list.indexOf(cl[i].against_sales_order) == -1) {
				prevdoc_list.push(cl[i].against_sales_order);
				if(prevdoc_list.length ==1)
					out += make_row("Sales Order", cl[i].against_sales_order, null, 0);
				else
					out += make_row('', cl[i].against_sales_order, null,0);
			}
		}
	}

	out +='</table></td></tr></table></div>';

	return out;
}

cur_frm.cscript.on_submit = function(doc, cdt, cdn) {
	if(cint(frappe.boot.notification_settings.delivery_note)) {
		cur_frm.email_doc(frappe.boot.notification_settings.delivery_note_message);
	}
}

if (sys_defaults.auto_accounting_for_stock) {

	cur_frm.cscript.expense_account = function(doc, cdt, cdn){
		var d = locals[cdt][cdn];
		if(d.expense_account) {
			var cl = doc["items"] || [];
			for(var i = 0; i < cl.length; i++){
				if(!cl[i].expense_account) cl[i].expense_account = d.expense_account;
			}
		}
		refresh_field("items");
	}

	// expense account
	cur_frm.fields_dict['items'].grid.get_field('expense_account').get_query = function(doc) {
		return {
			filters: {
				"report_type": "Profit and Loss",
				"company": doc.company,
				"is_group": 0
			}
		}
	}

	// cost center
	cur_frm.cscript.cost_center = function(doc, cdt, cdn){
		var d = locals[cdt][cdn];
		if(d.cost_center) {
			var cl = doc["items"] || [];
			for(var i = 0; i < cl.length; i++){
				if(!cl[i].cost_center) cl[i].cost_center = d.cost_center;
			}
		}
		refresh_field("items");
	}

	cur_frm.fields_dict.items.grid.get_field("cost_center").get_query = function(doc) {
		return {

			filters: {
				'company': doc.company,
				"is_group": 0
			}
		}
	}
}



