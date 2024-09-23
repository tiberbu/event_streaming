// Copyright (c) 2019, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Event Consumer", {
	refresh: function (frm) {
		// formatter for subscribed doctype approval status
		frm.set_indicator_formatter("status", function (doc) {
			let indicator = "orange";
			if (doc.status == "Approved") {
				indicator = "green";
			} else if (doc.status == "Rejected") {
				indicator = "red";
			}
			return indicator;
		});

		frm.add_custom_button(__('Set Host Name'), function () {
			let d = new frappe.ui.Dialog({
			  title: 'Enter URL details',
			  fields: [
				{
				  label: 'Site domain ie https://hmisv2.tiberbu.app',
				  fieldname: 'url',
				  fieldtype: 'Data'
				},
			  ],
			  size: 'small', // small, large, extra-large 
			  primary_action_label: 'Submit',
			  primary_action(values) {
				console.log(values);
				frappe.call({
				  method: "hmis.hmis.utilities.site_config.set_hostname",
				  args: {
					url: values.url
				  },
				  callback: r => {
	  
				  }
				}).then(r => {
				  frappe.msgprint(`Hostname  updated successfully`);
				  frm.reload_doc();
	  
				})
	  
				d.hide();
				d.hide();
			  }
			});
	  
			d.show();
		  });

	},
});
