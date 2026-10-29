
from frappe.frappeclient import FrappeClient
import frappe
from frappe.utils.data import now 
from frappe.utils.background_jobs import enqueue
from erpnext.controllers.item_variant import (
	get_variant,
)
import random
import string
import copy

source_client = None
target_client = None

# Registered sync doctypes in dependency order (parents before children):
# UOM before Item (stock_uom); Item Group before Item; Item Attribute +
# Item Alternative before Item (variants reference attribute values);
# SHA Intervention before Item; Item before Lab Test/Clinical Procedure
# Templates (they link Items); ICD11/Dictionary before Workflow/Health Program
# (they reference those concepts); Health Program before its Workflow/Field
# Mappings. Future doctypes: append here and to the page's doctypes array.
SYNC_DEPENDENCY_ORDER = [
    'Queue State Status',
    'UOM',
    'Item Group',
    'Item Attribute',
    'SHA Intervention',
    'Item Alternative',
    'Item',
    'Labs And Procedures Items',
    'Healthcare Service Unit Type',
    'Medical Department',
    'SHA Benefit Package',
    'Prescription Dosage',
    'Dosage Form',
    'Sample Type',
    'Lab Test UOM',
    'Dictionary Concept',
    'Concept FormKey Controls',
    'Lab Results Implications',
    'Signs And Symptoms',
    'ICD11 Collection',
    'Description Reports Mapping',
    'Lab Test Sample',
    'Lab Test Template',
    'Clinical Procedure Template',
    'Workflow',
    'Health Program',
    'Health Program Workflow',
    'Health Program Field Mapping',
]


@frappe.whitelist()
def run_all_syncs(producer_url='https://master.tiberbu.health', action='Update', mode='Merge'):
    """Run every registered doctype's Sync (insert) or Update in dependency
    order as one long background job. Per-doctype failures are logged and the
    run continues. Track with get_run_all_status(run_id)."""
    if action not in ("Sync", "Update"):
        action = "Update"
    if mode not in ("Merge", "Mirror"):
        mode = "Merge"
    run_id = now().replace(" ", "_").replace(":", "").replace(".", "") + "_" + str(frappe.generate_hash(length=6))
    payload = {
        "status": "Running",
        "action": action,
        "mode": mode,
        "total": len(SYNC_DEPENDENCY_ORDER),
        "current": 0,
        "current_doctype": None,
        "started": now(),
        "results": {},
    }
    frappe.cache().set_value(f"run_all:{run_id}", payload, expires_in_sec=24 * 3600)
    enqueue(method=_run_all_syncs, queue='long', timeout=21600,
            producer_url=producer_url, action=action, mode=mode, run_id=run_id)
    return {"run_id": run_id}


def _run_all_syncs(producer_url, action, mode, run_id):
    cache_key = f"run_all:{run_id}"
    state = frappe.cache().get_value(cache_key) or {"results": {}}
    for i, doctype in enumerate(SYNC_DEPENDENCY_ORDER, start=1):
        state.update({"current": i, "current_doctype": doctype})
        frappe.cache().set_value(cache_key, state, expires_in_sec=24 * 3600)
        started = now()
        try:
            if action == "Sync":
                insert_non_existing_records(producer_url, doctype)
            else:
                update_existing_records(producer_url, doctype, mode)
            state["results"][doctype] = {"status": "Completed", "started": started, "finished": now()}
        except Exception as e:
            frappe.log_error(f"Run All ({action}) failed for {doctype}: {e}", "Run All Failure")
            state["results"][doctype] = {"status": "Failed", "started": started, "finished": now()}
        frappe.cache().set_value(cache_key, state, expires_in_sec=24 * 3600)
    state.update({"status": "Completed", "current_doctype": None, "finished": now()})
    frappe.cache().set_value(cache_key, state, expires_in_sec=24 * 3600)


@frappe.whitelist()
def get_run_all_status(run_id):
    state = frappe.cache().get_value(f"run_all:{run_id}")
    if not state:
        return {"status": "Unknown", "message": "run expired or not found", "results": {}, "total": len(SYNC_DEPENDENCY_ORDER), "current": 0, "current_doctype": None}
    return state


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

    # fields that exist on BOTH servers (a field missing on the queried server
    # raises UnknownColumn and kills the whole sync)
    fields = get_sync_fields(source_client, target_client, doctype)
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
def update_existing_records(producer_url='https://master.tiberbu.health',doctype='Item Attribute',mode='Merge'):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get("source_client")
    target_client = clients.get("target_client")

    # 'Merge' (default): additive merge of child tables (keep local-only rows,
    # consolidate case-duplicates). 'Mirror': full replacement (old behavior) —
    # master's child rows replace the local ones exactly.
    if mode not in ("Merge", "Mirror"):
        mode = "Merge"

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

    # fields that exist on BOTH servers (a field missing on the queried server
    # raises UnknownColumn and kills the whole sync)
    fields = get_sync_fields(source_client, target_client, doctype)

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

            local_doc = None
            for child_field in child_table_fields:
                if mode == "Merge":
                    # additive: keep local-only rows, add/update from master
                    if local_doc is None:
                        local_doc = target_client.get_doc(doctype, name)
                    update_data[child_field] = merge_child_table(
                        local_doc.get(child_field) if local_doc else [],
                        source_doc.get(child_field),
                    )
                else:
                    # Mirror: replace local child rows with master's exactly
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
    # Item Variant Attribute.variant_of is a Link -> Item that master populates with
    # base-ingredient items (e.g. NYSTATIN) that are not synced to the target org,
    # so mirroring it makes every insert fail with LinkValidationError. The target
    # item's variant_of is already set on the parent, so this child field is dropped.
    drop_fields = ("variant_of",)
    cleaned = []
    for row in rows or []:
        if isinstance(row, dict):
            cleaned.append({k: v for k, v in row.items() if k not in system_fields and k not in drop_fields})
    return cleaned


# per-child-row fields that must not be copied across (Frappe sets/regenerates
# these); only business/value fields are merged.
_CHILD_ROW_SYSTEM_FIELDS = (
    "name", "owner", "creation", "modified", "modified_by",
    "parent", "parentfield", "parenttype", "idx", "docstatus",
)


def _child_row_key(row, fields):
    """Stable identity of a child row.

    Item Variant Attribute: unique by ``attribute`` (one row per attribute on a
    parent; the value may change, so it is not part of the key).
    Item Attribute Value: unique by ``attribute_value``. Frappe enforces
    uniqueness case-insensitively (Item Attribute.validate_duplication), so the
    key is lowercased too — otherwise the merge would keep a local row AND add
    a master row that differ only by case, which fails that same validation.
    """
    if "attribute" in fields:
        return ("attribute", row.get("attribute"))
    if "attribute_value" in fields:
        value = row.get("attribute_value")
        return ("attribute_value", str(value).lower() if value is not None else None)
    return tuple(row.get(f) for f in fields)


def _pick_canonical_row(rows):
    """Row to keep among local rows that differ only by case: the oldest one
    (by creation, then idx, then position)."""
    def sort_key(pair):
        i, row = pair
        return (row.get("creation") or "", row.get("idx") or 0, i)
    return min(enumerate(rows), key=sort_key)[1]


def merge_child_table(local_rows, source_rows):
    """Additively merge source child rows into local rows.

    - a local row matching a source row is updated in place (its `name` is
      preserved, so Frappe updates rather than delete+reinsert);
    - source rows with no local match are appended (nameless, so they insert);
    - local rows that differ from each other only by case are consolidated:
      the oldest row survives (converged to the source casing) and the extras
      are dropped, because Frappe validates these child rows case-insensitively
      and a case-duplicate pair fails the whole document save.
    """
    row_fields = set()
    for r in (local_rows or []) + (source_rows or []):
        if isinstance(r, dict):
            row_fields |= set(r.keys())
    value_fields = [f for f in row_fields if f not in _CHILD_ROW_SYSTEM_FIELDS]
    if not value_fields:
        return [copy.deepcopy(row) for row in (local_rows or []) if isinstance(row, dict)]

    merged = [copy.deepcopy(row) for row in (local_rows or []) if isinstance(row, dict)]
    local_by_key = {}
    for row in merged:
        local_by_key.setdefault(_child_row_key(row, value_fields), []).append(row)

    drop_ids = set()
    for src_row in source_rows or []:
        if not isinstance(src_row, dict):
            continue
        key = _child_row_key(src_row, value_fields)
        group = local_by_key.get(key)
        if group:
            keep = _pick_canonical_row(group)
            for f in value_fields:
                # a missing/None value from master means "not provided"; don't
                # clobber a local value with it
                src_val = src_row.get(f)
                if src_val is None or src_val == "":
                    continue
                keep[f] = src_val
            for extra in group:
                if extra is not keep:
                    drop_ids.add(id(extra))
        else:
            new_row = {f: src_row.get(f) for f in value_fields}
            merged.append(new_row)
            local_by_key.setdefault(key, []).append(new_row)

    # case-duplicate local rows that master has no row for: keep the oldest,
    # drop the rest (a self-duplicate fails the same case-insensitive check)
    for group in local_by_key.values():
        if len(group) > 1:
            keep = _pick_canonical_row(group)
            for extra in group:
                if extra is not keep:
                    drop_ids.add(id(extra))

    kept = [row for row in merged if id(row) not in drop_ids]
    for i, row in enumerate(kept):
        row["idx"] = i + 1
    return kept


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


def get_remote_doctype_fields(client, doctype_name):
    """Fieldnames of `doctype_name` as defined on the server `client` points to."""
    meta = client.get_doc("DocType", doctype_name)
    return [d.get("fieldname") for d in meta.get("fields", []) if d.get("fieldname")]


def get_sync_fields(source_client, target_client, doctype_name):
    """Fields that exist on BOTH source and target servers.

    Queries with a field that is missing on the queried server raise
    UnknownColumn errors, so only the intersection may be used. Ordering follows
    the target meta.
    """
    target_fields = get_doctype_fields(doctype_name)
    try:
        source_fields = set(get_remote_doctype_fields(source_client, doctype_name))
    except Exception as e:
        # if the DocType or its meta is unreachable, fail loudly with context
        raise RuntimeError(f"Could not read DocType {doctype_name} meta from source: {e}")
    if not source_fields:
        raise RuntimeError(f"DocType {doctype_name} has no fields on the source server")
    # standard Frappe system fields exist on every DocType; the DocType meta
    # `fields` list does not include them, so add them back explicitly
    system_fields = {
        "name", "owner", "creation", "modified", "modified_by", "idx",
        "docstatus", "parent", "parentfield", "parenttype",
    }
    source_fields |= system_fields
    common = [f for f in target_fields if f in source_fields]
    if not common:
        raise RuntimeError(f"No common fields between source and target for {doctype_name}")
    return common

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
    for key in ("app_url", "hostname", "host_name"):
        value = site_config.get(key)
        if value:
            return value
    port = site_config.get("webserver_port") or 8000
    return f"http://{frappe.local.site}:{port}"


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
