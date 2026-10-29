
from frappe.frappeclient import FrappeClient
import frappe
from frappe.utils.data import now 
from frappe.utils.background_jobs import enqueue
from erpnext.controllers.item_variant import (
	get_variant,
)
import random
import string

source_client = None
target_client = None

# bench execute event_streaming.event_streaming.api.frappe_client_transfers.execute_doctype_fetch_and_sync Clinical Procedure Template
@frappe.whitelist()
def execute_doctype_fetch_and_sync(producer_url='https://master.tiberbu.health',doctype='Item Group'):
    # insert_non_existing_records(producer_url,doctype)
    enqueue(method=insert_non_existing_records, queue='long', timeout=3600, producer_url=producer_url,doctype=doctype)


# bench execute hmis.hmis.setup.utility_frappe_client.insert_non_existing_records  filters={"creation": [">", '2024-10-30 11:18:43.421245']} filters={'name': ['like', '%physical%']} Health Program Field Mapping
def insert_non_existing_records(producer_url,doctype="Item Alternative"):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')
    filters={}
    if doctype == 'Item Alternative':
        doctype = "Item"
        # filters={'has_variants':1,'custom_is_ppb_drug':0,"disabled":0,"creation": ["between", ["2024-01-01", "2025-12-30"]]}
        filters = {"is_stock_item": 1, "has_variants": 1, "custom_is_ppb_drug": 1,"disabled":0}  # only clean drugs


    elif doctype == 'Item':
        # filters = {'has_variants':0,'custom_is_ppb_drug':0,"disabled":0,"creation": ["between", ["2024-01-01", "2025-12-30"]]}
        filters = {"is_stock_item": 1, "has_variants": 0, "custom_is_ppb_drug": 1,"disabled":0}
        
    elif doctype == 'Labs And Procedures Items':
        doctype = "Item"
        filters = {"is_stock_item": 0,"disabled":0}

    fields = get_doctype_fields(doctype)
    # print(fields)
    if 'custom_benefits_exchange_code' in fields:
        fields.remove('custom_benefits_exchange_code')

    target_filters = filters.copy()
    target_filters.pop("creation", None)

    list1 = target_client.get_list(doctype, fields=fields, limit_page_length=50000,filters=target_filters)
    list2 = source_client.get_list(doctype, fields=fields, limit_page_length=50000,filters=filters)
    
    
    target_names = {item['name'] for item in list1}
    source_names = {item['name'] for item in list2}

    items_in_source_not_in_target = source_names - target_names
    print(len(source_names))
    print(len(target_names))
    print(doctype," Items Missing In Source:",len(items_in_source_not_in_target))
    # print(items_in_source_not_in_target)
    
    try:
        child_table_fields = get_child_table_fields(doctype)
        batch_size = 1
        limit_start = 0
        num = 0
        filtered_list = [item for item in list2 if item['name'] in items_in_source_not_in_target]

        while True:
            # documents_batch = [item for item in list2 if item['name'] in items_in_source_not_in_target][limit_start:limit_start + batch_size]
            documents_batch = filtered_list[limit_start:limit_start + batch_size]


            if not documents_batch: 
                break

            docs_to_insert = []

            for document in documents_batch:
                num += 1
                item_name = document.get('name')
                print(num, item_name)

                if doctype == 'Item' and item_name in ['IBUPROFEN','Ibuprofen SUSPENSION-60ml','Aceclofenac/Paracetamol/','ALBENDAZOLE','METRONIDAZOLE','ATORVASTATIN CALCIUM','CHLORAMPHENICOL']:
                    print(f"Skipping problematic Item: {item_name}")
                    continue

                data = {
                    "doctype": doctype,
                    "docname": item_name
                }
                for field in fields:
                    data[field] = document.get(field)

                if child_table_fields:
                    parent_data = source_client.get_doc(doctype, item_name)
                    if parent_data:
                        if doctype in ('Clinical Procedure Template', 'Lab Test Template'):
                            data['link_existing_item'] = 1
                            remote_item = parent_data.get('item')
                            if remote_item:
                                local_item = target_client.get_doc("Item", remote_item)
                                if local_item:
                                    print(f"Item '{local_item}' exists locally.")
                                else:
                                    print(f"Item '{remote_item}' DOES NOT exist locally. Creating it...")
                                    target_client.insert({
                                        "doctype": "Item",
                                        "item_code": remote_item,
                                        "item_name": remote_item,
                                        "stock_uom": "Unit",
                                        "item_group": 'Services',
                                        "is_stock_item": 0,
                                    })

                        if doctype == 'SHA Intervention':
                            # payment_mechanism is a plain string field, not a child table
                            data["payment_mechanism"] = parent_data.get("payment_mechanism", "")

                        for child_field in child_table_fields:
                            data[child_field] = clean_child_rows(parent_data.get(child_field))

                print('add to insert ',data.get('name'))
                # if doctype == 'Item' and frappe.db.exists('Item',{'name':data.get('name')}):
                #     new_code = "{0}-1".format(data.get('item_code'))
                #     print('updating {0} to {1} docname {2}'.format(data.get('item_code'),new_code,data.get('name')))
                #     frappe.db.sql('UPDATE tabItem set item_code=%s where name=%s',[new_code,data.get('name')])
                #     frappe.db.commit()
                docs_to_insert.append(data)

            if docs_to_insert:
                print("Beginning bulk insert")
                try:
                    target_client.insert_many(docs_to_insert)
                    print(f"{len(docs_to_insert)} documents successfully inserted.")
                except Exception as insert_exception:
                    failed_name = docs_to_insert[0].get("name")
                    print(f"Insert failed for {failed_name}: {insert_exception}")
                    frappe.log_error(f"Insert failed for {doctype}/{failed_name}: {insert_exception}", "Sync Insert Failure")

            limit_start += batch_size
        

    except Exception as e:
        frappe.throw(f"An error occurred: {e}")

# bench execute event_streaming.event_streaming.api.frappe_client_transfers.update_existing_records
@frappe.whitelist()
def update_existing_records(producer_url='https://master.tiberbu.health',doctype='Item Attribute'):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get("source_client")
    target_client = clients.get("target_client")

    # is_procedure_template is_xray_and_imaging 'is_diagnosis':1
    filters = {}


    # filters=[
	# 			["modified", ">", "2025-07-06 08:56:26.272219"]
	# 		]
        
    if doctype == 'Item Alternative':
        doctype = "Item"
        filters = {"is_stock_item": 1, "has_variants": 1, "custom_is_ppb_drug": 1,"disabled":0}  # only clean drugs

    elif doctype == 'Item':
        filters = {"is_stock_item": 1, "has_variants": 0, "custom_is_ppb_drug": 1,"disabled":0}
        
    elif doctype == 'Labs And Procedures Items':
        doctype = "Item"
        filters = {"is_stock_item": 0,"disabled":0}

    fields = get_doctype_fields(doctype)

    source_list = source_client.get_list(doctype, fields=["name"], limit_page_length=50000, filters=filters)
    target_list = target_client.get_list(doctype, fields=["name"], limit_page_length=50000, filters=filters)

    source_names = {item["name"] for item in source_list}
    target_names = {item["name"] for item in target_list}

    common_names = source_names & target_names
    print(f"{len(common_names)} records found in both source and target to update")
    
    total = len(common_names)

    progress = frappe.get_doc({
        "doctype": "Data Sync Progress",
        "document_type": doctype,
        "total_records": total,
        "processed": 0,
        "success": 0,
        "failed": 0,
        "status": "Running",
        "synced_at":None
    })
    progress.insert(ignore_permissions=True)
    frappe.db.commit()
    
    child_table_fields = get_child_table_fields(doctype)
    num=0
    # return
    for name in common_names:
        try:
            source_doc = source_client.get_doc(doctype, name)
            if not source_doc:
                raise RuntimeError(f"Source document {doctype}/{name} not found on master")
            update_data = {
                "doctype": doctype,
                "name": name,
            }

            for field in fields:
                update_data[field] = source_doc.get(field)

            if doctype in ('Clinical Procedure Template', 'Lab Test Template'):
                remote_item = source_doc.get('item')
                if remote_item:
                    local_item = target_client.get_doc("Item", remote_item)
                    if not local_item:
                        print(f"Item '{remote_item}' DOES NOT exist locally. Creating it...")
                        target_client.insert({
                            "doctype": "Item",
                            "item_code": remote_item,
                            "item_name": remote_item,
                            "stock_uom": "Unit",
                            "item_group": 'Services',
                            "is_stock_item": 0,
                        })

            if doctype == 'SHA Intervention':
                # payment_mechanism is a plain string field, not a child table
                update_data["payment_mechanism"] = source_doc.get("payment_mechanism", "")

            for child_field in child_table_fields:
                update_data[child_field] = clean_child_rows(source_doc.get(child_field))
            # Perform the update
            clean_data = clean_update_data(update_data)
            target_client.update(clean_data)
            print(f"{num} Updated {name} successfully")
            num+=1
            
            progress.success += 1

        except Exception as e:
            frappe.log_error(f"Failed to update {name}: {e}", "Update Failure")

            progress.failed += 1
        
        finally:
            progress.processed += 1
            progress.save(ignore_permissions=True)
            frappe.db.commit()
            
    progress.synced_at = frappe.utils.now()
    progress.status = "Completed"
    progress.save(ignore_permissions=True)
    frappe.db.commit()

def get_child_table_fields(doctype_name):
    # taxes / reorder_levels / lab_test_groups / item_defaults are org-specific
    # settings, intentionally not mirrored (their Company/Warehouse/Account links
    # don't exist on the target org and would fail the whole insert)
    excluded = ("reorder_levels", "taxes", "lab_test_groups", "item_defaults")
    return [
        df.fieldname
        for df in frappe.get_meta(doctype_name).get_table_fields()
        if df.fieldname not in excluded
    ]


def clean_child_rows(rows):
    system_fields = ("name", "owner", "creation", "modified", "modified_by", "parent", "parentfield", "parenttype", "idx")
    cleaned = []
    for row in rows or []:
        if isinstance(row, dict):
            cleaned.append({k: v for k, v in row.items() if k not in system_fields})
    return cleaned


def clean_update_data(update_data):
    # Remove fields that cannot be updated
    for field in ["creation", "created_on", "created_by", "modified", "modified_by", "owner"]:
        update_data.pop(field, None)
    return update_data


# bench execute event_streaming.event_streaming.api.frappe_client_transfers.get_doctype_fields
def get_doctype_fields(doctype_name='Clinical Procedure Template'):
    meta = frappe.get_meta(doctype_name)
    field_list = [
            field.fieldname
            for field in meta.fields
            if field.fieldtype not in ["Column Break", "Section Break", "HTML", "Button", "Read Only", 
            "Fold", "Tab Break", "Image", "Geolocation", "Color","Table"]
        ]
    system_fields = ["name", "owner", "creation", "modified", "modified_by", "idx", "docstatus"]
        
    if meta.istable:
        system_fields.extend(["parent", "parentfield", "parenttype"])
        
    all_fields = field_list + system_fields
    final_fields = [item for item in all_fields if item not in ["remote_docname", "remote_site_name","reorder_levels","taxes","attributes","lab_test_groups"]]
    # print(final_fields)
    # print(len(final_fields))
    return(final_fields)

def get_source_and_target_frappe_client_obj(producer_url):
    producer_doc = frappe.get_doc("Event Producer", producer_url)
    source_client = FrappeClient(producer_url, api_key=producer_doc.api_key, api_secret=producer_doc.get_password("api_secret"))
    target_client = FrappeClient(get_host_name(), api_key=get_user_api_key(producer_doc.user).get('api_key'), api_secret=get_user_api_key(producer_doc.user).get('api_secret'))
    return {'source_client':source_client,'target_client':target_client}


# bench execute hmis.hmis.setup.frappe-client.get_user_api_key
def get_user_api_key(user):
    user = frappe.get_doc("User", user)
    if not user.api_key or not user.api_secret:
        return {"error": "API key or secret does not exist for this user."}
    return {"api_key": user.api_key, "api_secret": user.get_password('api_secret')}

def get_host_name():
    site_config = frappe.local.conf
    host_name = site_config.get('hostname', 'default_host_name')    
    return host_name


#  bench execute event_streaming.event_streaming.api.frappe_client_transfers.get_sync_status
@frappe.whitelist()
def old_get_sync_status(producer_url='https://master.tiberbu.health',doctype='Queue State Status'):
    filters={}
    
        
    if doctype == 'Item Alternative':
        doctype = "Item"
        filters = {"is_stock_item": 1, "has_variants": 1, "custom_is_ppb_drug": 1,"disabled":0}  # only clean drugs

    elif doctype == 'Item':
        filters = {"is_stock_item": 1, "has_variants": 0, "custom_is_ppb_drug": 1,"disabled":0}
        
    elif doctype == 'Labs And Procedures Items':
        doctype = "Item"
        filters = {"is_stock_item": 0,"disabled":0}

    
    target_filters = filters.copy()
    target_filters.pop("creation", None)

    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')

    source_count = len(source_client.get_list(doctype, fields=["name"],filters=filters,limit_page_length=50000))
    target_count = len(target_client.get_list(doctype, fields=["name"],filters=target_filters,limit_page_length=50000))
    print("SC: ",source_count,"TC:",target_count)
    percentage = (target_count / source_count * 100) if source_count != 0 else 0

    return {'current':target_count,'master':source_count,'percentage':percentage}


@frappe.whitelist()
def get_sync_status(producer_url='https://master.tiberbu.health', doctype='Queue State Status'):
    # Define filters for specific doctypes
    filters = {}
    if doctype == 'Item Alternative':
        doctype_query = "Item"
        filters = {"is_stock_item": 1, "has_variants": 1, "custom_is_ppb_drug": 1, "disabled": 0}
    elif doctype == 'Item':
        doctype_query = "Item"
        filters = {"is_stock_item": 1, "has_variants": 0, "custom_is_ppb_drug": 1, "disabled": 0}
    elif doctype == 'Labs And Procedures Items':
        doctype_query = "Item"
        filters = {"is_stock_item": 0, "disabled": 0}
    else:
        doctype_query = doctype

    # Copy filters for target, removing "creation" if exists
    target_filters = filters.copy()
    target_filters.pop("creation", None)

    # ----------------------------
    # Get latest Data Sync Progress
    # ----------------------------
    progress_list = frappe.get_all(
        "Data Sync Progress",
        filters={"document_type": doctype},
        order_by="creation desc",
        limit_page_length=1
    )

    if progress_list:
        progress_doc = frappe.get_doc("Data Sync Progress", progress_list[0].name)
        total = int(progress_doc.total_records or 0)
        processed = int(progress_doc.processed or 0)
        success = int(progress_doc.success or 0)
        failed = int(progress_doc.failed or 0)
        status = progress_doc.status
        synced_at = progress_doc.synced_at
        percentage_progress = (processed / total * 100) if total else 0
    else:
        total = processed = success = failed = 0
        status = "Not started"
        synced_at = None
        percentage_progress = 0

    # ----------------------------
    # Get live counts from source/target
    # ----------------------------
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')

    source_count = len(source_client.get_list(
        doctype_query,
        fields=["name"],
        filters=filters,
        limit_page_length=999999
    ))

    target_count = int(frappe.db.count(doctype_query, filters=target_filters))

    percentage = (target_count / source_count * 100) if source_count != 0 else 0


    # ----------------------------
    # Combine results
    # ----------------------------
    return {
            "current": target_count,
            "master": source_count,
            "percentage": percentage,
            "percentage_progress":percentage_progress,
            "success": success,
            "failed": failed,
            "status": status,
            "synced_at": synced_at  
    }


def get_fields(client, doctype):
    meta = client.get_doc("DocType", doctype)
    fields = [d.get('fieldname') for d in meta.get('fields') if d.get('fieldname')]
    fields.append('name')  # Always add 'name' because it's a primary field
    return fields
