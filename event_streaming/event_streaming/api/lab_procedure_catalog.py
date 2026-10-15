# Master catalog search + import for Lab Test Templates and
# Clinical Procedure Templates.
#
# This is a fresh, standalone implementation. It does not import or call
# any function from master_catalog_client.py. The only shared dependency
# is the FrappeClient auth pattern (Event Producer lookup), which is
# re-implemented here in _get_master_client() to keep this module
# self-contained.
#
# Flow:
#   1. search_lab_templates(term)      -> master Lab Test Templates
#   2. search_procedure_templates(term) -> master Clinical Procedure Templates
#   3. import_lab_template(code)        -> create Item if missing, then template
#   4. import_procedure_template(code)  -> create Item if missing, then template
#
# All four endpoints are whitelisted and callable from the frontend via
# the hmis facade (or directly if the hmis-lite frontend is configured
# to hit event_streaming).

import json

import frappe
from frappe import _
from frappe.frappeclient import FrappeClient


# ---------------------------------------------------------------------------
# Producer / client helpers (self-contained, not shared with drug code)
# ---------------------------------------------------------------------------


def _get_master_producer():
	"""Find and return the Event Producer record for the master instance."""
	producers = frappe.get_all(
		"Event Producer",
		filters={"producer_url": ["like", "%master%"]},
		fields=["name", "producer_url", "api_key", "api_secret"],
	)

	if not producers:
		frappe.throw(
			_(
				"No Event Producer configured for the master instance. "
				"An Event Producer record with a producer_url containing 'master' "
				"must exist on this site."
			)
		)

	if len(producers) > 1:
		frappe.log_error(
			title="Multiple master Event Producers found (lab/procedure)",
			message=(
				"Found {0} Event Producer records with 'master' in producer_url: {1}. "
				"Using the first one: {2}".format(
					len(producers),
					", ".join(p["name"] for p in producers),
					producers[0]["name"],
				)
			),
		)

	return producers[0]


def _get_master_client():
	"""Build and return a FrappeClient for the master instance."""
	producer = _get_master_producer()
	return FrappeClient(
		url=producer["producer_url"],
		api_key=producer["api_key"],
		api_secret=frappe.get_doc(
			"Event Producer", producer["name"]
		).get_password("api_secret"),
	)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@frappe.whitelist()
def search_lab_templates(search_term, limit=20):
	"""Search master Lab Test Templates by name or code.

	:param search_term: 2-100 character search term.
	:param limit: 1-50.
	:return: ``{"items": [...], "total": N}``
	"""
	if not search_term or len(search_term.strip()) < 2:
		frappe.throw("Search term must be at least 2 characters.")
	if len(search_term.strip()) > 100:
		frappe.throw("Search term must be at most 100 characters.")

	limit = max(1, min(int(limit), 50))
	search_term = search_term.strip()

	client = _get_master_client()
	response = client.get_api(
		"event_streaming.event_streaming.api.master_catalog_search.search_master_lab_templates",
		params={"search_term": search_term, "limit": limit},
	)

	if response is None:
		frappe.throw("Master instance returned an empty response.")

	if isinstance(response, str):
		try:
			response = json.loads(response)
		except ValueError:
			response = {}

	data = response or {}
	items = data.get("items", [])
	total = data.get("total", len(items))

	_enrich_lab_templates_with_local(items)

	return {"items": items, "total": total}


@frappe.whitelist()
def search_procedure_templates(search_term, limit=20):
	"""Search master Clinical Procedure Templates by name.

	:param search_term: 2-100 character search term.
	:param limit: 1-50.
	:return: ``{"items": [...], "total": N}``
	"""
	if not search_term or len(search_term.strip()) < 2:
		frappe.throw("Search term must be at least 2 characters.")
	if len(search_term.strip()) > 100:
		frappe.throw("Search term must be at most 100 characters.")

	limit = max(1, min(int(limit), 50))
	search_term = search_term.strip()

	client = _get_master_client()
	response = client.get_api(
		"event_streaming.event_streaming.api.master_catalog_search.search_master_procedure_templates",
		params={"search_term": search_term, "limit": limit},
	)

	if response is None:
		frappe.throw("Master instance returned an empty response.")

	if isinstance(response, str):
		try:
			response = json.loads(response)
		except ValueError:
			response = {}

	data = response or {}
	items = data.get("items", [])
	total = data.get("total", len(items))

	_enrich_procedures_with_local(items)

	return {"items": items, "total": total}


def _enrich_lab_templates_with_local(items):
	"""Batch-check which template codes already exist locally."""
	codes = [it["template_code"] for it in items]
	if not codes:
		for it in items:
			it["is_locally_available"] = False
		return

	local_codes = set(
		frappe.get_all("Lab Test Template", filters={"name": ["in", codes]}, pluck="name")
	)
	for it in items:
		it["is_locally_available"] = it["template_code"] in local_codes


def _enrich_procedures_with_local(items):
	"""Batch-check which template codes already exist locally."""
	codes = [it["template_code"] for it in items]
	if not codes:
		for it in items:
			it["is_locally_available"] = False
		return

	local_codes = set(
		frappe.get_all(
			"Clinical Procedure Template", filters={"name": ["in", codes]}, pluck="name"
		)
	)
	for it in items:
		it["is_locally_available"] = it["template_code"] in local_codes


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@frappe.whitelist()
def import_lab_template(template_code):
	"""Import a Lab Test Template from master into the local site.

	Creates the linked Item first if it doesn't exist, then creates the
	Lab Test Template with its child tables.

	:param template_code: the Lab Test Template name on master.
	:return: dict with success, template_code, item_code, item_created, message
	"""
	if not template_code or not str(template_code).strip():
		frappe.throw("Template code is required.")
	template_code = str(template_code).strip()

	client = _get_master_client()

	# Fetch the full template doc from master
	remote_doc = client.get_doc("Lab Test Template", template_code)
	if not remote_doc:
		frappe.throw("Lab Test Template {0} not found on master.".format(template_code))

	# Check if template already exists locally
	if frappe.db.exists("Lab Test Template", template_code):
		return {
			"success": True,
			"status": "already_exists",
			"template_code": template_code,
			"item_code": remote_doc.get("item") or "",
			"item_created": False,
			"message": "Lab Test Template {0} already exists locally.".format(template_code),
		}

	# Create the linked Item if it doesn't exist locally
	item_code = (remote_doc.get("item") or "").strip()
	item_created = False
	if item_code:
		if not frappe.db.exists("Item", item_code):
			remote_item = client.get_doc("Item", item_code)
			if remote_item:
				item_created = _create_local_item(item_code, remote_item)
		# If item exists locally or creation failed, continue — the template
		# will be created with the item link as-is.

	# Create the Lab Test Template locally
	_template = _sanitize_lab_template_dict(remote_doc)
	_template["name"] = template_code
	_template["item"] = item_code
	# Tell the healthcare app's after_insert hook that the Item already exists
	# so it skips its own item creation (which would cause a duplicate error).
	_template["link_existing_item"] = 1
	# Prevent the on_update hook from trying to re-save the Item we just created
	# (it would fail on duplicate UOM entries in the conversion factor table).
	_template["change_in_item"] = 0

	doc = frappe.get_doc(_template)
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()

	return {
		"success": True,
		"status": "imported",
		"template_code": template_code,
		"item_code": item_code,
		"item_created": item_created,
		"message": "Lab Test Template {0} imported successfully.".format(template_code),
	}


@frappe.whitelist()
def import_procedure_template(template_code):
	"""Import a Clinical Procedure Template from master into the local site.

	Creates the linked Item first if it doesn't exist, then creates the
	Clinical Procedure Template with its child tables.

	:param template_code: the Clinical Procedure Template name on master.
	:return: dict with success, template_code, item_code, item_created, message
	"""
	if not template_code or not str(template_code).strip():
		frappe.throw("Template code is required.")
	template_code = str(template_code).strip()

	client = _get_master_client()

	remote_doc = client.get_doc("Clinical Procedure Template", template_code)
	if not remote_doc:
		frappe.throw(
			"Clinical Procedure Template {0} not found on master.".format(template_code)
		)

	if frappe.db.exists("Clinical Procedure Template", template_code):
		return {
			"success": True,
			"status": "already_exists",
			"template_code": template_code,
			"item_code": remote_doc.get("item") or "",
			"item_created": False,
			"message": "Clinical Procedure Template {0} already exists locally.".format(
				template_code
			),
		}

	item_code = (remote_doc.get("item") or "").strip()
	item_created = False
	# Pre-create the Item so the template's `item` Link field validates.
	# The healthcare app's Clinical Procedure Template has an after_insert hook
	# (create_item_from_template) that would normally auto-create the Item, but
	# we set `item` to empty below so the hook skips that and we avoid a
	# duplicate item_code IntegrityError.
	if item_code:
		if not frappe.db.exists("Item", item_code):
			remote_item = client.get_doc("Item", item_code)
			if remote_item:
				item_created = _create_local_item(item_code, remote_item)

	_proc = _sanitize_procedure_template_dict(remote_doc)
	_proc["name"] = template_code
	_proc["item"] = item_code
	# Tell the healthcare app's after_insert hook that the Item already exists
	# so it skips its own item creation (which would cause a duplicate error).
	_proc["link_existing_item"] = 1

	doc = frappe.get_doc(_proc)
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()

	# Now link the pre-created item to the template
	if item_code:
		frappe.db.set_value("Clinical Procedure Template", template_code, "item", item_code)
		frappe.db.commit()

	return {
		"success": True,
		"status": "imported",
		"template_code": template_code,
		"item_code": item_code,
		"item_created": item_created,
		"message": "Clinical Procedure Template {0} imported successfully.".format(
			template_code
		),
	}


# ---------------------------------------------------------------------------
# Sanitisation helpers
# ---------------------------------------------------------------------------


def _sanitize_lab_template_dict(remote_doc):
	"""Convert a remote Lab Test Template dict into a local-ready dict."""
	remote = dict(remote_doc or {})

	for key in (
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"docstatus_timestamp",
		"_assign",
		"_comments",
		"_liked_by",
		"_user_tags",
		"idx",
	):
		remote.pop(key, None)

	# Keep child tables as-is (normal_test_templates, lab_test_groups, etc.)
	# Strip idx from each row
	for key in (
		"normal_test_templates",
		"lab_test_groups",
		"descriptive_test_templates",
		"codification_table",
	):
		if key in remote and isinstance(remote[key], list):
			for row in remote[key]:
				row.pop("idx", None)

	return remote


def _sanitize_procedure_template_dict(remote_doc):
	"""Convert a remote Clinical Procedure Template dict into a local-ready dict."""
	remote = dict(remote_doc or {})

	for key in (
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"docstatus_timestamp",
		"_assign",
		"_comments",
		"_liked_by",
		"_user_tags",
		"idx",
	):
		remote.pop(key, None)

	# Keep child tables
	for key in ("items", "codification_table"):
		if key in remote and isinstance(remote[key], list):
			for row in remote[key]:
				row.pop("idx", None)

	return remote


def _create_local_item(item_code, remote_item):
	"""Create a local Item from a remote Item dict.

	Strips server-managed fields and site-specific child tables.
	:return: True if created, False if it already existed or failed.
	"""
	remote = dict(remote_item or {})

	for key in (
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"docstatus_timestamp",
		"_assign",
		"_comments",
		"_liked_by",
		"_user_tags",
		"idx",
	):
		remote.pop(key, None)

	for key in (
		"barcodes",
		"item_defaults",
		"supplier_items",
		"unit_of_measure_conversion",
		"taxes",
		"serial_nos_and_batches",
		"uoms",
	):
		remote.pop(key, None)

	# Normalise attributes child table
	raw_attrs = remote.get("attributes") or []
	clean_attrs = []
	for a in raw_attrs:
		val = a.get("attribute_value")
		if val and str(val).strip():
			clean_attrs.append(
				{
					"attribute": a.get("attribute", ""),
					"attribute_value": str(val),
				}
			)
	remote["attributes"] = clean_attrs

	remote["name"] = item_code
	remote["item_code"] = item_code

	try:
		doc = frappe.get_doc(remote)
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.commit()
		return True
	except Exception as e:
		frappe.log_error(
			title="Lab/Procedure import: Item creation failed",
			message="item_code={0} error={1}".format(item_code, e),
		)
		return False
