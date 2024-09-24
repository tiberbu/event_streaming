// Copyright (c) 2019, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Event Producer", {
	refresh: function (frm) {
		frm.set_query("ref_doctype", "producer_doctypes", function () {
			return {
				filters: {
					issingle: 0,
					istable: 0,
				},
			};
		});

		if (frm.doc.producer_doctypes) {
            frm.doc.producer_doctypes.forEach(function(row) {
                if (row.ref_doctype) {
                    frappe.call({
                        method: "hmis.hmis.setup.frappe-client.get_sync_status",
                        args: {
							producer_url: row.parent,
                            doctype: row.ref_doctype
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.model.set_value(row.doctype, row.name, "master_count", r.message.master);
								frappe.model.set_value(row.doctype, row.name, "current_count", r.message.current);
								frappe.model.set_value(row.doctype, row.name, "percentage", r.message.percentage);
                                frm.refresh_field("producer_doctypes");
                            }
                        }
                    });
                }
            });
        }

		frm.set_indicator_formatter("status", function (doc) {
			let indicator = "orange";
			if (doc.status == "Approved") {
				indicator = "green";
			} else if (doc.status == "Rejected") {
				indicator = "red";
			}
			return indicator;
		});
	}
});

frappe.ui.form.on('Event Producer Document Type', {
    sync_from_master(frm, cdt, cdn) {
        let row = frappe.get_doc(cdt, cdn);
        frappe.call({
                method: "hmis.hmis.setup.frappe-client.execute_doctype_fetch_and_sync",
                args: {
				  producer_url:row.parent,
                  doctype:row.ref_doctype
                },
                callback: r => {
                    
                }
            }).then(r=>{
                frappe.msgprint('Syncing started....');
                frm.reload_doc();
                
            })
        
    },
	
});