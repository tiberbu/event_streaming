import frappe
from frappe.model.document import Document

class DataSyncSettings(Document):
	pass

# bench execute event_streaming.event_streaming.doctype.data_sync_settings.data_sync_settings.prepopulate_sync_doctypes
def prepopulate_sync_doctypes():
	regular_sync_doctypes = {
		'Item Group','Concept FormKey Controls','ICD11 Collection','Dictionary Concept',
		'Health Program','Health Program Workflow','Health Program Field Mapping','Workflow'
	}
	update_sync_doctypes = {'Item Alternative', 'Item'}

	all_doctypes = [
		'Queue State Status','Item Group','UOM','SHA Intervention','Item Attribute',
		'Item Alternative','Item','Labs And Procedures Items','Healthcare Service Unit Type',
		'Medical Department','SHA Benefit Package','Clinical Procedure Template','Lab Test UOM',
		'Concept FormKey Controls','Dictionary Concept','Lab Results Implications',
		'Lab Test Template','Prescription Dosage','Dosage Form',
		'Health Program','Health Program Workflow','Health Program Field Mapping',
		'Workflow','Signs And Symptoms','ICD11 Collection','Description Reports Mapping'
	]

	settings = frappe.get_single("Data Sync Settings")
	settings.sync_doctypes = []

	for dt in all_doctypes:
		settings.append("sync_doctypes", {
			"document_type": dt,
			"insert_sync": 1,
			"update_sync": 1 if dt in update_sync_doctypes else 0,
			"regular_sync": 1 if dt in regular_sync_doctypes else 0,
		})

	settings.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"Prepopulated {len(all_doctypes)} doctypes in Data Sync Settings")
