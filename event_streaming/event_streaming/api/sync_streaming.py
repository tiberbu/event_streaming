import frappe
import hashlib
import json

def extract_human_error(trace):
    lines = [l.strip() for l in trace.splitlines() if l.strip()]

    # walk backwards to find last exception-looking line
    for line in reversed(lines):
        if ":" in line:
            return line.split(":", 1)[1].strip()

    return "Unknown error"

#  bench execute event_streaming.event_streaming.api.sync_streaming.get_latest_event_stream_error
@frappe.whitelist()
def get_latest_event_stream_error():
    title = "event_streaming.event_streaming.api.frappe_client_transfers.insert_non_existing_records"

    # fetch latest matching error log
    error_log = frappe.get_all(
        "Error Log",
        filters={"method": title,"seen":0},
        fields=["name", "error","creation"],
        order_by="creation desc",
        limit=1
    )

    if not error_log:
        return "No matching error log found."

    name = error_log[0].get("name", "Unknown")
    trace = error_log[0].get("error", "")
    creation_time = str(error_log[0].get("creation", "Unknown time"))[:-7]

    if not trace:
        return {
            "error": "Error log found but no traceback available.",
            "creation_time": creation_time,
            "name": name
        }

    return {
        "error": extract_human_error(trace),
        "creation_time": creation_time,
        "name": name
    }

#  bench execute event_streaming.event_streaming.api.sync_streaming.mark_error_as_seen
@frappe.whitelist()
def mark_error_as_seen(name):
    if not name:
        return "No error log name provided."

    try:
        frappe.db.set_value("Error Log", name, "seen", 1)
        frappe.db.commit()
        return f"Error log '{name}' marked as seen."
    except Exception as e:
        return f"Failed to mark error log as seen: {str(e)}"    

#  bench execute event_streaming.event_streaming.api.sync_streaming.clear_resolved_uom_case_errors
@frappe.whitelist()
def clear_resolved_uom_case_errors():
    """Mark as seen the stale Error Logs from the UOM case-sensitivity insert
    storm (e.g. "1062 Duplicate entry '100S' for key 'uom_name'"), which the
    case-insensitive insert-diff fix resolved. The banner
    (get_latest_event_stream_error) only shows unseen rows, so marking these
    seen clears it. The matching is scoped to the 'key 'uom_name'' 1062
    signature on the insert method, so unrelated 1062 dupes (key PRIMARY:
    Blood Grouping, debridement) and other signatures are left untouched.
    Idempotent — re-running marks whatever is still unseen."""
    title = "event_streaming.event_streaming.api.frappe_client_transfers.insert_non_existing_records"
    rows = frappe.get_all("Error Log", filters={"method": title, "seen": 0}, fields=["name", "error"])
    to_clear = [
        r.name for r in rows
        if "1062" in (r.error or "") and "key 'uom_name'" in (r.error or "")
    ]
    for name in to_clear:
        frappe.db.set_value("Error Log", name, "seen", 1)
    if to_clear:
        frappe.db.commit()
    return {"marked_seen": len(to_clear), "unseen_total": len(rows)}

def _referenced_names(doctype):
    """Every `doctype` name that another doctype links to (top-level link fields
    and child-table link fields), so a dedupe never deletes a referenced row."""
    referenced = set()
    link_fields = frappe.get_all(
        "DocField",
        filters={"fieldtype": "Link", "options": doctype},
        fields=["parent", "parentfield", "fieldname"],
    )
    for lf in link_fields:
        if lf.parentfield:
            # field inside a child table: find the child doctype, then that field's values
            child_dt = frappe.db.get_value("DocField", {"parent": lf.parent, "fieldname": lf.parentfield}, "options")
            if not child_dt:
                continue
            source = frappe.db.get_all(child_dt, filters={lf.fieldname: ["is", "set"]}, fields=[lf.fieldname])
        else:
            source = frappe.db.get_all(lf.parent, filters={lf.fieldname: ["is", "set"]}, fields=[lf.fieldname])
        for row in source:
            if row.get(lf.fieldname):
                referenced.add(row.get(lf.fieldname))
    return referenced


#  bench execute event_streaming.event_streaming.api.sync_streaming.dedupe_master_sync_duplicates Description Reports Mapping
@frappe.whitelist()
def dedupe_master_sync_duplicates(doctype):
    """Collapse the exact-duplicate rows the old sync piled up (it re-inserted the
    same record every run under a new auto-generated name). Only byte-identical
    copies (parent fields + child tables) are removed. Safety: a row that is
    referenced by any other doctype is NEVER deleted, and when a group has no
    referenced copy the oldest one is kept. Idempotent — re-running is a no-op
    once the duplicates are gone."""
    meta = frappe.get_meta(doctype)
    noncol = {"Section Break", "Column Break", "Table", "Button", "Heading", "HTML", "Image", "JSON", "Multiselect"}
    pfields = [f.fieldname for f in meta.fields if f.fieldtype not in noncol]
    dbc = {r[0] for r in frappe.db.sql("DESCRIBE `tab%s`" % doctype)}
    pfields = [f for f in pfields if f in dbc]
    child = [(f.fieldname, f.options) for f in meta.fields if f.fieldtype == "Table" and f.options]

    def sig(name):
        d = frappe.get_all(doctype, filters={"name": name}, fields=pfields)
        parent = d[0] if d else {}
        kids = {}
        for cf, dt in child:
            rows = frappe.db.get_all(dt, filters={"parent": name}, fields=["*"])
            kids[cf] = sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
        return hashlib.sha1(json.dumps({"p": parent, "c": kids}, sort_keys=True, default=str).encode()).hexdigest()

    all_rows = frappe.db.get_all(doctype, fields=["name", "creation", "owner"])
    groups = {}
    for r in all_rows:
        groups.setdefault(sig(r.name), []).append(r)

    referenced = _referenced_names(doctype)
    deleted, collapsed = [], 0
    for grp in groups.values():
        if len(grp) < 2:
            continue
        collapsed += 1
        referenced_in_grp = [r for r in grp if r.name in referenced]
        if referenced_in_grp:
            keep = referenced_in_grp  # never delete a referenced copy
        else:
            keep = [sorted(grp, key=lambda r: (r.creation or "", r.name))[0]]  # keep oldest
        keep_names = {k.name for k in keep}
        for r in grp:
            if r.name not in keep_names:
                frappe.delete_doc(doctype, r.name, ignore_permissions=True)
                deleted.append(r.name)
    if deleted:
        frappe.db.commit()
    return {
        "doctype": doctype,
        "duplicate_groups": collapsed,
        "deleted": len(deleted),
        "remaining": len(all_rows) - len(deleted),
    }


#  bench execute event_streaming.event_streaming.api.sync_streaming.snoop_doctype_syncing_via_cron
@frappe.whitelist()
def snoop_doctype_syncing_via_cron():
    from ..crons.setup import run_instance_setup
    return {
        "name": run_instance_setup(True),
        "current_count": 0,
        "master_count": 0,
        "percentage": 0,
        "percentage_progress": 0,
        "success": 0,
        "failed": 0,
        "status": "",
        "last_synced": None
    }

#  bench execute event_streaming.event_streaming.api.sync_streaming.get_setup_cron_status
@frappe.whitelist()
def get_setup_cron_status():
    stopped = frappe.db.get_value("Scheduled Job Type", "setup.run_instance_setup","stopped")
    if stopped:
        return "Disabled"
    return "Active"

#  bench execute event_streaming.event_streaming.api.sync_streaming.toggle_setup_cron_status
@frappe.whitelist()
def toggle_setup_cron_status():
    stopped = frappe.db.get_value("Scheduled Job Type", "setup.run_instance_setup", "stopped")
    new_stopped = 0 if stopped else 1
    frappe.db.set_value("Scheduled Job Type", "setup.run_instance_setup", "stopped", new_stopped)
    frappe.db.commit()
    return "Disabled" if new_stopped else "Active"