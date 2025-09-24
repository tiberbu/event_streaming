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
                        method: "event_streaming.event_streaming.api.frappe_client_transfers.get_sync_status",
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

        // Show initial alert
        frappe.show_alert({
            message: __('Syncing has started...'),
            indicator: 'green'
        }, 5);

        let started = false;
        let interval = setInterval(() => {
            frappe.call({
                method: "event_streaming.event_streaming.api.frappe_client_transfers.get_sync_status",
                args: {
                    producer_url: row.parent,
                    doctype: row.ref_doctype
                },
                callback: function(status) {
                    if (status.message) {
                        let percentage = status.message.percentage || 0;
                        logProgress(percentage)

                        if (!started && percentage > 0) {
                            started = true;
                            console.log("Sync has started!");
                        }

                        frappe.show_progress('Syncing...', percentage, 100, 'Please wait while syncing');

                        // Stop polling if sync is 100%
                        if (percentage >= 100) {
                            clearInterval(interval);
                            frappe.show_alert({
                                message: __('Sync Completed!'),
                                indicator: 'green'
                            }, 5);
                            frm.reload_doc();
                        }
                    }
                }
            });
        }, 1000); // Poll every 1 second

        // **Then** trigger the actual sync request
        frappe.call({
            method: "event_streaming.event_streaming.api.frappe_client_transfers.execute_doctype_fetch_and_sync",
            args: {
                producer_url: row.parent,
                doctype: row.ref_doctype
            }
        });
    },
    update_from_master(frm, cdt, cdn) {
        let row = frappe.get_doc(cdt, cdn);

        // Show initial alert
        frappe.show_alert({
            message: __('Updating has started...'),
            indicator: 'green'
        }, 5);

        // **Then** trigger the actual update request
        frappe.call({
            method: "event_streaming.event_streaming.api.frappe_client_transfers.update_existing_records",
            args: {
                producer_url: row.parent,
                doctype: row.ref_doctype
            }
        });
    }
});


function logProgress(percentage) {
    const totalBars = 20;
    const completedBars = Math.floor((percentage / 100) * totalBars);
    const remainingBars = totalBars - completedBars;
    const progressBar = `[${"#".repeat(completedBars)}${"-".repeat(remainingBars)}]`;

    console.log(`%c${progressBar} ${percentage}%`, "color: green; font-weight: bold; font-size: 14px;");
}

