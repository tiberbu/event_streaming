import frappe

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