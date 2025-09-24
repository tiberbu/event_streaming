import frappe
from datetime import datetime, date, timedelta
from frappe.installer import update_site_config

from ..api.frappe_client_transfers import get_sync_status,execute_doctype_fetch_and_sync, get_source_and_target_frappe_client_obj
# bench execute event_streaming.event_streaming.crons.setup.run_instance_setup
def run_instance_setup():
    doctypes =['Queue State Status','Item Group','UOM','SHA Intervention','Item Attribute','Item Alternative','Item','Healthcare Service Unit Type','Medical Department',
               'Clinical Procedure Template','Lab Test UOM','Concept FormKey Controls','Dictionary Concept','Lab Results Implications','Lab Test Template','Prescription Dosage','Dosage Form',
               'Health Program','Health Program Workflow','Health Program Field Mapping','Workflow','Signs And Symptoms',
               'ICD11 Collection','Description Reports Mapping']
    master_url = "https://master.tiberbu.health"
    
    # check status of the last doctype (Description Reports Mapping)
    final_status = get_sync_status(master_url, "Description Reports Mapping").get("percentage", 0)

    # if fully synced, only allow run every 1 hour
    if final_status > 95:
        last_run_str = frappe.conf.LAST_RUN_KEY
        if last_run_str:
            last_run = datetime.fromisoformat(last_run_str)
            if datetime.now() < last_run + timedelta(hours=1):
                frappe.logger().info("Skipping run_instance_setup: already complete and last run <1h ago")
                print("skipping")
                return

        # update last run time
        update_site_config('LAST_RUN_KEY', datetime.now().isoformat(), validate=True)
    
    for doctype in doctypes:
        status = get_sync_status(master_url, doctype).get('percentage', 0)
        print(f"Sync status for {doctype}: {status}%")
        if status < 100:
            print("run the sync for", doctype)
            add_progress_comment(f"Syncing {doctype} from Master", f"Syncing {doctype} from Master is at {round(status,0)} percent")
            execute_doctype_fetch_and_sync(master_url, doctype)
            break

# bench execute event_streaming.event_streaming.crons.setup.regularly_sync_essential_doctypes
def regularly_sync_essential_doctypes():
    master_url = "https://master.tiberbu.health"
    doctypes =['Concept FormKey Controls','ICD11 Collection','Dictionary Concept','Health Program','Health Program Workflow',
               'Health Program Field Mapping','Workflow']
    for doctype in doctypes:
        status = get_sync_status(master_url, doctype).get('percentage', 0)
        print(f"Sync status for {doctype}: {status}%")
        if status < 100:
            print("run the sync for", doctype)
            add_progress_comment(f"Syncing {doctype} from Master", f"Syncing {doctype} from Master is at {round(status,0)} percent")
            execute_doctype_fetch_and_sync(master_url, doctype)
    

def add_progress_comment(subject,text):
	doc = frappe.new_doc("Comment")
	doc.comment_type = "Comment"
	doc.subject = subject
	doc.content = text
	doc.save()
 
# bench execute event_streaming.event_streaming.crons.setup.create_missing_item_groups
def create_missing_item_groups():
    
    # Rename Laboratory
    frappe.rename_doc("Item Group", "Laboratory", "LABORATORY-temp")
    frappe.rename_doc("Item Group", "LABORATORY-temp", "LABORATORY")
    
    missing_item_groups = ['All Drugs','Biochemistry','Radiology and Imaging Services','Renal Function Tests(Electrolytes)','PARASITOLOGY','HAEMATOLOGY']
    for ig in missing_item_groups:
        if not frappe.db.exists("Item Group", ig):
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = ig
            item_group.parent_item_group = "Biochemistry" if ig=='Renal Function Tests(Electrolytes)' else "All Item Groups"
            item_group.is_group = 1 if ig == 'All Drugs' else 0
            item_group.insert()
            print(f"Created missing Item Group: {ig}")
        else:
            print(f"Item Group {ig} already exists.")
            


# bench execute event_streaming.event_streaming.crons.setup.create_missing_item_groups_remotely
def create_missing_item_groups_remotely(producer_url='https://master.tiberbu.health'):
    client = get_source_and_target_frappe_client_obj(producer_url)["target_client"]
    
    # Rename Laboratory -> LABORATORY-temp -> LABORATORY
    try:
        client.rename_doc("Item Group", "Laboratory", "LABORATORY-temp")
        client.rename_doc("Item Group", "LABORATORY-temp", "LABORATORY")
        print("Renamed 'Laboratory' to 'LABORATORY'")
    except Exception as e:
        print(f"Rename failed: {e}")

    missing_item_groups = [
        'All Drugs',
        'Biochemistry',
        'Radiology and Imaging Services',
        'Renal Function Tests(Electrolytes)',
        'PARASITOLOGY',
        'HAEMATOLOGY'
    ]

    for ig in missing_item_groups:
        exists = client.get_value("Item Group", filters={"name": ig})
        if not exists:
            doc = {
                "doctype": "Item Group",
                "item_group_name": ig,
                "parent_item_group": "Biochemistry" if ig == 'Renal Function Tests(Electrolytes)' else "All Item Groups",
                "is_group": 1 if ig == 'All Drugs' else 0
            }
            client.insert(doc)
            print(f"Created missing Item Group remotely: {ig}")
        else:
            print(f"Item Group {ig} already exists on remote.")
    # create SHA customer
    exists1 = client.get_value("Customer", filters={"customer_name": 'Social Health Authority'})
    if not exists1:
        doc1 = {
                    "doctype": "Customer",
                    "customer_name": 'Social Health Authority',
                    "customer_type": 'Company'
                }
        client.insert(doc1)
        
    exists2 = client.get_value("Customer Group", filters={"customer_group_name": 'Social Health Authority'})
    if not exists2:
        doc2 = {
                    "doctype": "Customer Group",
                    "customer_group_name": 'Social Health Authority',
                    "parent_customer_group": 'Commercial',
                    "is_health_scheme":1,
                    "default_price_list":'Standard Selling',
                    "default_customer":"Social Health Authority"
                }
        client.insert(doc2)
        

# bench execute event_streaming.event_streaming.crons.setup.sync_frequent_updated_doctypes
def sync_frequent_updated_doctypes():
    master_url = "https://master.tiberbu.health"
    doctypes=['Dictionary Concept','Health Program','Health Program Workflow','Health Program Field Mapping','Workflow','Signs And Symptoms']
    # get items less than 15 days old from master

# bench execute event_streaming.event_streaming.crons.setup.post_new_additions_to_master
def post_new_additions_to_master():
    master_url = "https://master.tiberbu.health"
    doctype=['Signs And Symptoms']
    # use after insert?
    
