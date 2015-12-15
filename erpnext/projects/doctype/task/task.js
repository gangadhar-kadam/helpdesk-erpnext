// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.projects");

cur_frm.add_fetch("project", "company", "company");

frappe.ui.form.on("Task", {
	refresh: function(frm) {
		var doc = frm.doc;
		if(doc.__islocal) {
			if(!frm.doc.exp_end_date) {
				frm.set_value("exp_end_date", frappe.datetime.add_days(new Date(), 7));
			}
		}


		if(!doc.__islocal) {
			if(frappe.model.can_read("Time Log")) {
				frm.add_custom_button(__("Time Logs"), function() {
					frappe.route_options = {"project": doc.project, "task": doc.name}
					frappe.set_route("List", "Time Log");
				}, "icon-list", true);
			}
			if(frappe.model.can_read("Expense Claim")) {
				frm.add_custom_button(__("Expense Claims"), function() {
					frappe.route_options = {"project": doc.project, "task": doc.name}
					frappe.set_route("List", "Expense Claim");
				}, "icon-list", true);
			}

			if(frm.perm[0].write) {
				if(frm.doc.status!=="Closed" && frm.doc.status!=="Cancelled") {
					frm.add_custom_button("Close", function() {
						frm.set_value("status", "Closed");
						frm.save();
					});
				} else {
					frm.add_custom_button("Reopen", function() {
						frm.set_value("status", "Open");
						frm.save();
					});
				}
			}
		}
	},

	setup: function(frm) {
		frm.fields_dict.project.get_query = function() {
			return {
				query: "erpnext.projects.doctype.task.task.get_project"
			}
		};
	},

	project: function(frm) {
		if(frm.doc.project) {
			return get_server_fields('get_project_details', '','', frm.doc, frm.doc.doctype,
				frm.doc.name, 1);
		}
	},

	validate: function(frm) {
		frm.doc.project && frappe.model.remove_from_locals("Project",
			frm.doc.project);
	},

});

cur_frm.add_fetch('task', 'subject', 'subject');
