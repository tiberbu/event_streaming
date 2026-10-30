
from frappe.frappeclient import FrappeClient
import frappe
from frappe.utils.data import now
from frappe.utils import cstr
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


def _latest_sync_progress(doctype):
    """Freshest Data Sync Progress row for a doctype (the one the live job is
    writing to), as a dict, or None if the job hasn't created one yet."""
    return frappe.db.get_value(
        "Data Sync Progress",
        {"document_type": doctype},
        ["name", "total_records", "processed", "success", "failed", "status", "synced_at"],
        order_by="creation desc",
        as_dict=True,
    )


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
            result = {"status": "Completed", "started": started, "finished": now()}
        except Exception as e:
            frappe.log_error(f"Run All ({action}) failed for {doctype}: {e}", "Run All Failure")
            result = {"status": "Failed", "started": started, "finished": now()}
        progress = _latest_sync_progress(doctype)
        if progress:
            result["success"] = int(progress.get("success") or 0)
            result["failed"] = int(progress.get("failed") or 0)
        state["results"][doctype] = result
        frappe.cache().set_value(cache_key, state, expires_in_sec=24 * 3600)
    state.update({"status": "Completed", "current_doctype": None, "finished": now()})
    frappe.cache().set_value(cache_key, state, expires_in_sec=24 * 3600)


@frappe.whitelist()
def get_run_all_status(run_id):
    state = frappe.cache().get_value(f"run_all:{run_id}")
    if not state:
        return {"status": "Unknown", "message": "run expired or not found", "results": {}, "total": len(SYNC_DEPENDENCY_ORDER), "current": 0, "current_doctype": None}
    # record-level progress of the doctype that is running right now
    if state.get("status") == "Running" and state.get("current_doctype"):
        progress = _latest_sync_progress(state["current_doctype"])
        state["current_progress"] = (
            {
                "document_type": state["current_doctype"],
                "total_records": int(progress.get("total_records") or 0),
                "processed": int(progress.get("processed") or 0),
                "success": int(progress.get("success") or 0),
                "failed": int(progress.get("failed") or 0),
                "status": progress.get("status"),
            }
            if progress
            else None
        )
    else:
        state["current_progress"] = None
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
    original_doctype = doctype
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

    # Diff by name only, then fetch full docs just for the missing records.
    # (Fetching every field for every row truncates the diff at the page limit
    # and loads unbounded data into memory — wrong for any large doctype.)
    target_names = {item['name'] for item in target_client.get_list(doctype, fields=["name"], limit_page_length=999999, filters=target_filters)}
    source_names = {item['name'] for item in source_client.get_list(doctype, fields=["name"], limit_page_length=999999, filters=filters)}

    # A record is "missing" only when its STABLE identity is absent locally.
    # Most doctypes key on name (case-insensitive: the unique index uses a
    # case-insensitive collation, so "100S" vs "100s" is already present). Three
    # doctypes need a different key because their stored name is unreliable:
    #   Item: the diff above uses a filtered local set (disabled=0, ...), but the
    #     name key is global — an item present yet filtered out is still "taken"
    #     and re-inserting 1062s. Key on the full local name set (item_code is
    #     unreliable: it gets suffixed -1 by the dedup logic while the name stays).
    #   Description Reports Mapping: the name auto-generates on insert
    #     (MAPPING-{description}-{#####}), so it is never stable — the name diff
    #     re-inserts the same reports every run, piling up unbounded duplicates.
    #     Key on description instead (idempotent: once present, skipped).
    #   Health Program Field Mapping: the name is {form_name}-{form_field_name};
    #     a malformed master name (empty field) still regenerates to a name that
    #     already exists locally, so the insert 1062s. Key on the field pair.
    if doctype == "Item":
        target_lower = {cstr(item.get("name")).lower() for item in target_client.get_list(doctype, fields=["name"], limit_page_length=999999)}
        items_in_source_not_in_target = {n for n in source_names if cstr(n).lower() not in target_lower}
    elif original_doctype == "Description Reports Mapping":
        src = source_client.get_list(doctype, fields=["name", "description"], limit_page_length=999999, filters=filters)
        tgt_keys = {cstr(r.get("description")).lower() for r in target_client.get_list(doctype, fields=["description"], limit_page_length=999999)}
        items_in_source_not_in_target = {r["name"] for r in src if cstr(r.get("description")).lower() not in tgt_keys}
    elif original_doctype == "Health Program Field Mapping":
        src = source_client.get_list(doctype, fields=["name", "form_name", "form_field_name"], limit_page_length=999999, filters=filters)
        tgt = target_client.get_list(doctype, fields=["name", "form_name", "form_field_name"], limit_page_length=999999)
        # present if the name OR the generated {form_name}-{form_field_name}
        # already exists locally (local copies sometimes carry a tweaked
        # form_field_name, e.g. apgarScore vs apgarScore1, so the generated name
        # alone does not always reconstruct)
        tgt_names = {cstr(r.get("name")).lower() for r in tgt}
        tgt_pairs = {f"{cstr(r.get('form_name'))}-{cstr(r.get('form_field_name'))}".lower() for r in tgt}
        items_in_source_not_in_target = {
            r["name"] for r in src
            if cstr(r.get("name")).lower() not in tgt_names
            and f"{cstr(r.get('form_name'))}-{cstr(r.get('form_field_name'))}".lower() not in tgt_pairs
        }
    else:
        target_lower = {cstr(n).lower() for n in target_names}
        items_in_source_not_in_target = {n for n in source_names if cstr(n).lower() not in target_lower}
    list2 = source_client.get_list(doctype, fields=fields, limit_page_length=999999, filters=filters)
    print(len(source_names))
    print(len(target_names))
    print(doctype," Items Missing In Source:",len(items_in_source_not_in_target))

    # progress row for the live job (document_type keeps the original doctype so
    # the per-doctype status endpoint keeps working for Item's sub-filters)
    progress = frappe.get_doc({
        "doctype": "Data Sync Progress",
        "document_type": original_doctype,
        "total_records": len(items_in_source_not_in_target),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "status": "Running",
        "synced_at": None
    })
    progress.insert(ignore_permissions=True)
    frappe.db.commit()
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
            skipped_docs = 0

            for document in documents_batch:
                num += 1
                item_name = document.get('name')
                print(num, item_name)

                if doctype == 'Item' and item_name in ['IBUPROFEN','Ibuprofen SUSPENSION-60ml','Aceclofenac/Paracetamol/','ALBENDAZOLE','METRONIDAZOLE','ATORVASTATIN CALCIUM','CHLORAMPHENICOL']:
                    print(f"Skipping problematic Item: {item_name}")
                    skipped_docs += 1
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

                # master carries duplicate UOM Conversion rows (e.g. two "Unit"
                # rows); inserting them fails the UOM uniqueness validation, so
                # keep the first of each (case-folded) UOM — same key
                # merge_child_table uses
                if doctype == 'Item' and data.get("uoms"):
                    seen = set()
                    deduped = []
                    for row in data["uoms"]:
                        key = str(row.get("uom") or "").lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        deduped.append(row)
                    data["uoms"] = deduped

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
                    progress.success += len(docs_to_insert)
                except Exception as insert_exception:
                    failed_name = docs_to_insert[0].get("name")
                    print(f"Insert failed for {failed_name}: {insert_exception}")
                    frappe.log_error(f"Insert failed for {doctype}/{failed_name}: {insert_exception}", "Sync Insert Failure")
                    progress.failed += len(docs_to_insert)

            progress.processed += len(docs_to_insert) + skipped_docs
            progress.save(ignore_permissions=True)
            frappe.db.commit()

            limit_start += batch_size

    except Exception as e:
        frappe.log_error(f"An error occurred during {doctype} insert: {e}", "Sync Insert Failure")
        raise
    finally:
        progress.synced_at = now()
        progress.status = "Completed"
        progress.save(ignore_permissions=True)
        frappe.db.commit()

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
        
    original_doctype = doctype
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
        "document_type": original_doctype,
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
                # name vanished from the master after the snapshot was taken —
                # skip, it is not a sync failure
                print(f"Skipping {name}: not found on master")
                frappe.log_error(f"Source document {doctype}/{name} not found on master", "Sync Source Missing")
                raise SkipRecord()
            update_data = {
                "doctype": doctype,
                "name": name,
            }

            for field in fields:
                update_data[field] = source_doc.get(field)

            # series is set_only_once: on auto-named doctypes it is fixed at
            # creation, and the source's value often differs from the local one
            # (auto-numbering diverged). Copying it over trips
            # CannotChangeConstantError on every such update — the name can't
            # change on an update anyway, so keep the local series.
            if update_data.get("series"):
                local_series = frappe.db.get_value(doctype, name, "series")
                if cstr(local_series) != cstr(update_data["series"]):
                    update_data.pop("series")

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

            # NestedSet doctypes (Item Group, ...): the parent's is_group and
            # the lft/rgt tree bookkeeping must stay in sync with the children
            # that ACTUALLY exist on this server. Master may have the same node
            # as a leaf (is_group=0) with different lft/rgt, and copying that
            # over a node that has children locally fails NestedSet
            # validate_ledger ("cannot be a leaf node as it has children").
            meta = frappe.get_meta(doctype)
            parent_field = getattr(meta, "nsm_parent_field", None)
            if parent_field and "is_group" in update_data:
                has_children = bool(frappe.db.count(doctype, {parent_field: name}))
                update_data["is_group"] = 1 if has_children else (source_doc.get("is_group") or 0)
                for tree_field in ("lft", "rgt", "old_parent"):
                    update_data.pop(tree_field, None)

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

            if doctype == "Item":
                _apply_item_update_guards(update_data)

            # Perform the update
            clean_data = clean_update_data(update_data)
            target_client.update(clean_data)
            print(f"{num} Updated {name} successfully")
            num+=1
            
            progress.success += 1

        except SkipRecord:
            # logged at the raise site; counted as processed (finally) but not failed
            pass
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

# fields dropped from child rows on copy (variant_of on Item Variant Attribute
# references master-only items — see clean_child_rows)
_CHILD_ROW_DROP_FIELDS = ("variant_of",)


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
    if "uom" in fields:
        # UOM Conversion.uom is validated case-insensitively (UOM doctype
        # duplicate check); lowercase so a case-duplicate pair converges
        value = row.get("uom")
        return ("uom", str(value).lower() if value is not None else None)
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
    value_fields = [f for f in row_fields if f not in _CHILD_ROW_SYSTEM_FIELDS and f not in _CHILD_ROW_DROP_FIELDS]
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
        # dropped fields are excluded from value_fields but the deep-copied local
        # rows still carry them; strip from output so a poisoned/stale link (e.g.
        # Item Variant Attribute.variant_of -> a master-only item) is never re-sent,
        # which would otherwise fail the whole save with LinkValidationError.
        for f in _CHILD_ROW_DROP_FIELDS:
            row.pop(f, None)
        row["idx"] = i + 1
    return kept


def clean_update_data(update_data):
    # Remove fields that cannot be updated
    for field in ["creation", "created_on", "created_by", "modified", "modified_by", "owner"]:
        update_data.pop(field, None)
    return update_data


class SkipRecord(Exception):
    """A record to skip (data gap or stale snapshot); not a sync failure."""


def _stock_uom_change_is_blocked(item_code, new_uom):
    """Mirror of erpnext's check_stock_uom_with_bin: True when local
    Stock Ledger Entry / Bin state rejects a stock_uom change."""
    current_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    if not new_uom or cstr(new_uom) == cstr(current_uom):
        return False
    ref_uom = frappe.db.get_value("Stock Ledger Entry", {"item_code": item_code}, "stock_uom")
    if ref_uom and cstr(ref_uom) != cstr(new_uom):
        return True
    blocked_bins = frappe.db.sql(
        "SELECT name FROM `tabBin` WHERE item_code = %s "
        "AND (reserved_qty > 0 OR ordered_qty > 0 OR indented_qty > 0 OR planned_qty > 0) "
        "AND stock_uom != %s",
        (item_code, new_uom),
    )
    return bool(blocked_bins)


def _dedupe_item_uom_rows(update_data):
    # the master's UOM Conversion table carries duplicate rows (both same-case
    # dupes like two "Unit" and case-dupes like "60s"/"60S"); Item.validate
    # rejects a UOM listed more than once. Merge mode already converges via
    # _child_row_key, but Mirror mode replaces the local rows with master's
    # exactly, so the master's own duplicates still reach the save — keep the
    # first of each (case-folded) UOM.
    rows = update_data.get("uoms")
    if not rows:
        return
    seen = set()
    deduped = []
    for row in rows:
        key = cstr(row.get("uom")).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    update_data["uoms"] = deduped


def _apply_item_update_guards(update_data):
    """Item-only pre-update safety nets for erpnext validations a master
    payload would trip:
    - stock_uom: drop the change when local transactions block it
    - uoms: drop duplicate UOM Conversion rows (case-folded)
    - attributes: a variant's rows must exist on the local template; drop rows
      the local template lacks, and skip the record if nothing usable remains
      for a variant/template with variant_based_on 'Item Attribute'
    """
    name = update_data.get("name")

    _dedupe_item_uom_rows(update_data)

    if _stock_uom_change_is_blocked(name, update_data.get("stock_uom")):
        frappe.log_error(
            f"{name}: stock_uom change to {update_data.get('stock_uom')} is blocked by local transactions; keeping local UOM",
            "Sync Skipped",
        )
        update_data.pop("stock_uom", None)

    variant_of = update_data.get("variant_of")
    attrs = update_data.get("attributes")
    if variant_of and attrs:
        template_attrs = {
            r[0]
            for r in frappe.db.get_all(
                "Item Variant Attribute", filters={"parent": variant_of}, pluck="attribute"
            )
        }
        attrs = [row for row in attrs if row.get("attribute") in template_attrs]
        update_data["attributes"] = attrs
    if (variant_of or update_data.get("has_variants")) and update_data.get("variant_based_on") == "Item Attribute" and not attrs:
        frappe.log_error(
            f"{name}: variant_based_on is 'Item Attribute' but no usable attribute rows (master/template data gap); skipping update",
            "Sync Skipped",
        )
        raise SkipRecord()


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
    # Get live names from source/target (a set difference, not a count ratio)
    # ----------------------------
    # A count ratio (target_count / source_count) saturates once the target has
    # as many rows as the source and can exceed 100% when the target holds extra
    # records — so it cannot tell "fully synced" apart from "missing N specific
    # records." The real completeness signal is the set difference: records that
    # exist on the source but are absent on the target.
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')

    source_names = {row["name"] for row in source_client.get_list(
        doctype_query,
        fields=["name"],
        filters=filters,
        limit_page_length=999999
    )}

    target_names = {row.get("name") for row in frappe.db.get_all(
        doctype_query,
        filters=target_filters,
        fields=["name"],
    )}

    # "missing" = source records whose STABLE identity is absent locally. Most
    # doctypes key on name (case-insensitive — the unique index uses a
    # case-insensitive collation). Three doctypes need a different key because
    # the stored name is unreliable (keeps the dashboard and the actual sync in
    # agreement, so the percentage reaches 100 once covered and the cron stops
    # re-triggering):
    #   Item: key on the FULL local name set (a filtered-out item is still
    #     "covered"; item_code alone is unreliable — suffixed -1 by dedup).
    #   Description Reports Mapping: name auto-generates on insert
    #     (MAPPING-{description}-{#####}), so the name never matches and the
    #     diff re-inserts the same reports forever. Key on description.
    #   Health Program Field Mapping: name is {form_name}-{form_field_name}; a
    #     malformed master name still regenerates to an existing local name and
    #     1062s. Key on the field pair.
    if doctype_query == "Item":
        tgt_keys = {cstr(r.get("name")).lower() for r in frappe.db.get_all("Item", fields=["name"])}
        src_records = source_client.get_list(doctype_query, fields=["name"], filters=filters, limit_page_length=999999)
        missing = {r["name"] for r in src_records if cstr(r.get("name")).lower() not in tgt_keys}
    elif doctype_query == "Description Reports Mapping":
        tgt_keys = {cstr(r.get("description")).lower() for r in frappe.db.get_all("Description Reports Mapping", fields=["description"])}
        src_records = source_client.get_list(doctype_query, fields=["name", "description"], filters=filters, limit_page_length=999999)
        missing = {r["name"] for r in src_records if cstr(r.get("description")).lower() not in tgt_keys}
    elif doctype_query == "Health Program Field Mapping":
        tgt = frappe.db.get_all("Health Program Field Mapping", fields=["name", "form_name", "form_field_name"])
        # present if the name OR the generated {form_name}-{form_field_name}
        # already exists locally (local copies sometimes carry a tweaked
        # form_field_name, e.g. apgarScore vs apgarScore1, so the generated name
        # alone does not always reconstruct)
        tgt_names = {cstr(r.get("name")).lower() for r in tgt}
        tgt_pairs = {f"{cstr(r.get('form_name'))}-{cstr(r.get('form_field_name'))}".lower() for r in tgt}
        src_records = source_client.get_list(doctype_query, fields=["name", "form_name", "form_field_name"], filters=filters, limit_page_length=999999)
        missing = {
            r["name"] for r in src_records
            if cstr(r.get("name")).lower() not in tgt_names
            and f"{cstr(r.get('form_name'))}-{cstr(r.get('form_field_name'))}".lower() not in tgt_pairs
        }
    else:
        tgt_keys = {cstr(n).lower() for n in target_names}
        missing = {n for n in source_names if cstr(n).lower() not in tgt_keys}

    source_count = len(source_names)
    target_count = len(target_names)
    # coverage of the source set by the target; capped at 100, 0 when nothing to sync
    percentage = ((source_count - len(missing)) / source_count * 100) if source_count else 0

    # ----------------------------
    # Combine results
    # ----------------------------
    return {
            "current": target_count,
            "master": source_count,
            "percentage": percentage,
            "percentage_progress":percentage_progress,
            "missing": len(missing),
            "present": source_count - len(missing),
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
