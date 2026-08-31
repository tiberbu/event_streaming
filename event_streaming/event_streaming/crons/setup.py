import frappe
from datetime import datetime, date, timedelta
from frappe.installer import update_site_config

from ..api.frappe_client_transfers import get_sync_status,execute_doctype_fetch_and_sync, update_existing_records, get_source_and_target_frappe_client_obj

def get_sync_settings():
    """Read sync configuration from Data Sync Settings doctype."""
    settings = frappe.get_single("Data Sync Settings")
    return settings

def get_doctypes_for(sync_type):
    """Get list of doctypes enabled for a given sync type (insert_sync, update_sync, regular_sync)."""
    settings = get_sync_settings()
    return [row.document_type for row in settings.sync_doctypes if getattr(row, sync_type, 0)]

def get_master_url():
    return frappe.get_single("Data Sync Settings").master_url or "https://master.tiberbu.health"

# bench execute event_streaming.event_streaming.crons.setup.run_instance_setup
def run_instance_setup(snooping=False):
    doctypes = get_doctypes_for("insert_sync")
    if not doctypes:
        print("No doctypes configured for insert sync")
        return
    master_url = get_master_url()

    # check status of the last configured doctype
    final_status = get_sync_status(master_url, doctypes[-1]).get("percentage", 0)

    # if fully synced, only allow run every 1 hour
    if final_status >= 100:
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
            if snooping:
                return doctype
            add_progress_comment(f"Syncing {doctype} from Master", f"Syncing {doctype} from Master is at {round(status,0)} percent")
            execute_doctype_fetch_and_sync(master_url, doctype)
            break

# bench execute event_streaming.event_streaming.crons.setup.regularly_sync_essential_doctypes
def regularly_sync_essential_doctypes():
    doctypes = get_doctypes_for("regular_sync")
    if not doctypes:
        print("No doctypes configured for regular sync")
        return
    master_url = get_master_url()

    # check status of the last configured doctype
    final_status = get_sync_status(master_url, doctypes[-1]).get("percentage", 0)

    # if fully synced, only allow run every 1 hour
    if final_status >= 100:
        last_run_str = frappe.conf.get("REGULAR_SYNC_LAST_RUN")
        if last_run_str:
            last_run = datetime.fromisoformat(last_run_str)
            if datetime.now() < last_run + timedelta(hours=1):
                frappe.logger().info("Skipping regularly_sync_essential_doctypes: already complete and last run <1h ago")
                print("skipping regular sync")
                return

        update_site_config('REGULAR_SYNC_LAST_RUN', datetime.now().isoformat(), validate=True)

    for doctype in doctypes:
        status = get_sync_status(master_url, doctype).get('percentage', 0)
        print(f"Sync status for {doctype}: {status}%")
        if status < 100:
            print("run the sync for", doctype)
            add_progress_comment(f"Syncing {doctype} from Master", f"Syncing {doctype} from Master is at {round(status,0)} percent")
            execute_doctype_fetch_and_sync(master_url, doctype)
            break
    

# bench execute event_streaming.event_streaming.crons.setup.run_update_sync
def run_update_sync():
    """Update existing records from master. Processes one doctype per run.
    If a doctype is still Running (from a previous run), it resumes it.
    If completed, moves to the next one."""
    doctypes = get_doctypes_for("update_sync")
    if not doctypes:
        print("No doctypes configured for update sync")
        return
    master_url = get_master_url()

    for doctype in doctypes:
        # Check if this doctype already has a "Running" progress — resume it
        running = frappe.get_all(
            "Data Sync Progress",
            filters={"document_type": doctype, "status": "Running"},
            limit_page_length=1
        )
        if running:
            # Check if another process is actively working on it (modified in last 10 minutes)
            progress_doc = frappe.get_doc("Data Sync Progress", running[0].name)
            last_modified = frappe.utils.get_datetime(progress_doc.modified)
            if frappe.utils.now_datetime() - last_modified < timedelta(minutes=10):
                print(f"Skipping {doctype}: another process is still active (last updated {last_modified})")
                break

            print(f"Resuming update for {doctype}...")
            try:
                update_existing_records(master_url, doctype)
            except Exception as e:
                print(f"Failed to resume {doctype}: {e}")
                frappe.log_error(f"Update sync failed for {doctype}: {e}", "Update Sync Error")
            break

        # Check if this doctype has been completed — uncheck update_sync and skip
        completed = frappe.get_all(
            "Data Sync Progress",
            filters={"document_type": doctype, "status": "Completed"},
            limit_page_length=1
        )
        if completed:
            settings = get_sync_settings()
            for row in settings.sync_doctypes:
                if row.document_type == doctype:
                    row.update_sync = 0
                    break
            settings.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Update sync completed for {doctype}, unchecked update_sync flag")
            continue

        # Not started yet — start it
        print(f"Starting update for {doctype}...")
        try:
            add_progress_comment(f"Updating {doctype} from Master", f"Running update sync for {doctype}")
            update_existing_records(master_url, doctype)
        except Exception as e:
            print(f"Failed to update {doctype}: {e}")
            frappe.log_error(f"Update sync failed for {doctype}: {e}", "Update Sync Error")
        break


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
            frappe.db.commit()
            print(f"Created missing Item Group: {ig}")
        else:
            print(f"Item Group {ig} already exists.")
            
    # Create SHA Customer if missing
    if not frappe.db.exists("Customer", {"customer_name": "Social Health Authority"}):
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Social Health Authority"
        customer.customer_type = "Company"
        customer.insert()
        frappe.db.commit()
        print("Created Customer: Social Health Authority")
    else:
        print("Customer 'Social Health Authority' already exists.")
    
    # Create SHA Customer Group if missing
    if not frappe.db.exists("Customer Group", {"customer_group_name": "Social Health Authority"}):
        customer_group = frappe.new_doc("Customer Group")
        customer_group.customer_group_name = "Social Health Authority"
        customer_group.parent_customer_group = "Commercial"
        customer_group.is_health_scheme = 1
        customer_group.default_price_list = "Standard Selling"
        customer_group.default_customer = "Social Health Authority"
        customer_group.insert()
        frappe.db.commit()
        print("Created Customer Group: Social Health Authority")
    else:
        print("Customer Group 'Social Health Authority' already exists.")


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

# bench execute event_streaming.event_streaming.crons.setup.set_item_allow_rename_attribute
def set_item_allow_rename_attribute():
    doc = frappe.get_single("Item Variant Settings")
    doc.allow_rename_attribute_value = 1
    doc.save()
    frappe.db.commit()

# bench execute event_streaming.event_streaming.crons.setup.set_item_allow_rename_attribute_remotely
def set_item_allow_rename_attribute_remotely(producer_url='https://master.tiberbu.health'):
    target_client = get_source_and_target_frappe_client_obj(producer_url)["target_client"]
    try:
        item_variant_settings = target_client.get_doc("Item Variant Settings", "Item Variant Settings")
        item_variant_settings["allow_rename_attribute_value"] = 1
        target_client.update(item_variant_settings)
        print("Successfully enabled 'Allow Rename Attribute Value' on remote site.")
    except Exception as e:
        print("Failed to update remote Item Variant Settings:", e)
        
