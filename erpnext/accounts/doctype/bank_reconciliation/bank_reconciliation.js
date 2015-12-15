// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Bank Reconciliation", {
	setup: function(frm) {
		frm.get_docfield("journal_entries").allow_bulk_edit = 1;
		frm.add_fetch("bank_account", "account_currency", "account_currency");
	},

	onload: function(frm) {
		frm.set_query("bank_account", function() {
			return {
				"filters": {
					"account_type": "Bank",
					"is_group": 0
				}
			};
		});

		frm.set_value("from_date", frappe.datetime.month_start());
		frm.set_value("to_date", frappe.datetime.month_end());
	},

	refresh: function(frm) {
		frm.disable_save();
	},

	update_clearance_date: function(frm) {
		return frappe.call({
			method: "update_details",
			doc: frm.doc
		});
	},
	get_relevant_entries: function(frm) {
		return frappe.call({
			method: "get_details",
			doc: frm.doc,
			callback: function(r, rt) {
				frm.refresh()
			}
		});
	}
});
