# Date Validation


	frappe.ui.form.on("Event", "validate", function(frm) {
        if (frm.doc.from_date < get_today()) {
            msgprint(__("You can not select past date in From Date"));
            throw "past date selected"
        }
	});

{next}
