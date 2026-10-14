# Dev-site client for the master catalog.
#
# The frontend never talks to the master instance directly. All calls go:
#
#   frontend -> hmis facade (hmis.hmis.billing.items.items)
#             -> this module (event_streaming)
#             -> master instance via FrappeClient
#
# This module runs on the dev site and uses the "Event Producer" record
# whose producer_url contains "master" to build the authenticated client.

import json

import frappe
from frappe import _
from frappe.frappeclient import FrappeClient

MASTER_ENDPOINT_SEARCH = (
	"event_streaming.event_streaming.api.master_catalog_search.search_master_items"
)

# Attribute names recognised when importing variants. Mapped to the
# hmis Item Attribute doctype names so that the attribute values can be
# registered locally before the variant is created.
_ATTRIBUTE_MAP = {
	"DRUG STRENGTH": ("DRUG STRENGTH", "append_strength"),
	"Brand Name": ("Brand Name", "append_to_brand_name"),
	"DRUG FORM": ("DRUG FORM", "append_to_form"),
	"Drug Route": ("Drug Route", "append_drug_route"),
}


# ---------------------------------------------------------------------------
# Producer / client helpers
# ---------------------------------------------------------------------------


def _get_master_producer():
	"""Find and return the Event Producer record for the master instance.

	Raises a clear error when zero producers match. When more than one
	match, the first is used and a warning is logged.
	"""
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
				"must exist on this site before the master catalog can be used."
			)
		)

	if len(producers) > 1:
		frappe.log_error(
			title="Multiple master Event Producers found",
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


def _bespoke_field_exists_local() -> bool:
	"""Check whether the bespoke custom field exists on THIS site."""
	return bool(
		frappe.db.exists(
			"Custom Field", {"fieldname": "custom_is_bespoke_drug", "dt": "Item"}
		)
	)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _enrich_with_local_availability(items):
	"""Batch-check which item_codes already exist locally and stamp each
	result dict with an ``is_locally_available`` boolean."""
	codes = [it["item_code"] for it in items]
	if not codes:
		for it in items:
			it["is_locally_available"] = False
		return

	local_codes = set(frappe.get_all("Item", filters={"name": ["in", codes]}, pluck="name"))

	for it in items:
		it["is_locally_available"] = it["item_code"] in local_codes


@frappe.whitelist()
def search_master_catalog(search_term, limit=20):
	"""Search the master catalog and return results enriched with local
	availability.

	:param search_term: drug name search term (2-100 chars).
	:param limit: 1-50.
	:return: ``{"items": [...], "total": N}`` where each item has
	          ``is_locally_available`` (bool) added.
	"""
	if not search_term or len(search_term.strip()) < 2:
		frappe.throw("Search term must be at least 2 characters.")
	if len(search_term.strip()) > 100:
		frappe.throw("Search term must be at most 100 characters.")

	limit = max(1, min(int(limit), 50))
	search_term = search_term.strip()

	client = _get_master_client()
	response = client.get_api(
		MASTER_ENDPOINT_SEARCH,
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

	_enrich_with_local_availability(items)

	return {"items": items, "total": total}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _register_variant_attribute(attribute_name, attribute_value):
	"""Register an attribute value under the given Item Attribute if it
	does not already exist, so the variant's attributes child table is
	valid. Silently skips attributes that are not in the known map."""
	mapping = _ATTRIBUTE_MAP.get(attribute_name)
	if not mapping:
		return
	_attr_doctype, _helper_name = mapping
	if not attribute_value:
		return
	# The append helpers live in hmis; import lazily to avoid a hard dep
	# at module load time.
	from hmis.hmis.clinical.terminology.drug_item import (
		append_drug_route,
		append_strength,
		append_to_brand_name,
		append_to_form,
	)

	helper = {
		"append_strength": append_strength,
		"append_to_brand_name": append_to_brand_name,
		"append_to_form": append_to_form,
		"append_drug_route": append_drug_route,
	}.get(_helper_name)

	if helper:
		try:
			helper(str(attribute_value))
		except Exception as e:
			frappe.log_error(
				title="Master catalog import: attribute registration failed",
				message="attribute={0!r} value={1!r} error={2}".format(
					attribute_name, attribute_value, e
				),
			)


def _sanitize_item_dict(remote_doc):
	"""Convert a remote Item dict (from get_doc / get_master_item) into a
	local-ready dict: strip server-managed fields and normalise the
	attributes child table."""
	remote = dict(remote_doc or {})

	# Server-managed / site-specific fields that must not be copied.
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

	# Child tables that carry site-specific data are dropped.
	for key in (
		"barcodes",
		"item_defaults",
		"supplier_items",
		"unit_of_measure_conversion",
		"taxes",
		"serial_nos_and_batches",
		"uoms",
		"custom_terminology_codes",
	):
		remote.pop(key, None)

	# Normalise attributes child table: keep only fields the local Item
	# variant doc needs. Drop rows where attribute_value is empty.
	raw_attrs = remote.get("attributes") or []
	clean_attrs = []
	for a in raw_attrs:
		val = a.get("attribute_value")
		if not val or not str(val).strip():
			continue
		clean_attrs.append(
			{
				"attribute": a.get("attribute", ""),
				"attribute_value": str(val),
			}
		)
	remote["attributes"] = clean_attrs

	return remote


def _create_local_item(item_code, item_dict, template_created=False):
	"""Create (or verify existence of) an Item locally from a master item dict.

	Handles both templates (has_variants=1) and variants. For variants
	whose template does not yet exist locally, the template is created
	first (idempotent).

	Flags (custom_is_ppb_drug / custom_is_bespoke_drug) are copied from
	the master item. For a variant, the effective flag is:
	  variant flag OR template flag   (per flag)

	:return: dict with success info, or raises.
	"""
	bespoke_local = _bespoke_field_exists_local()

	# --- Resolve effective flags ---
	pending = (
		bool(item_dict.get("custom_is_ppb_drug")) or 0,
		bool(item_dict.get("custom_is_bespoke_drug")) if bespoke_local else 0,
	)

	template_code = (item_dict.get("variant_of") or "").strip()
	template_created_flag = False

	if template_code:
		# Variant: check template exists locally; create it if not
		if not frappe.db.exists("Item", template_code):
			client = _get_master_client()
			remote_template = client.get_doc("Item", template_code)
			if not remote_template:
				frappe.throw(
					"Template {0} not found on master — cannot import variant {1}.".format(
						template_code, item_code
					)
				)
			# Recursively create the template (should be a template, no variant_of)
			_create_local_item(template_code, remote_template)
			template_created_flag = True

		# Fetch local template flags for OR-ing
		template_ppb = frappe.db.get_value(
			"Item", template_code, "custom_is_ppb_drug"
		) or 0
		template_bespoke = (
			frappe.db.get_value(
				"Item", template_code, "custom_is_bespoke_drug"
			)
			if bespoke_local
			else 0
		) or 0
		pending = (
			1 if (pending[0] or template_ppb) else 0,
			1 if (pending[1] or template_bespoke) else 0,
		)

	# --- Build the local item doc ---
	local_dict = _sanitize_item_dict(item_dict)
	local_dict["name"] = item_code
	local_dict["item_code"] = item_code

	# Variant / template shape: a variant keeps variant_of and never
	# carries the template-level attributes definitions; a template has no
	# variant_of. (has_variants already comes from the master doc.)
	if not template_code:
		local_dict.pop("variant_of", None)
	else:
		local_dict["variant_of"] = template_code
		if not local_dict.get("attributes"):
			local_dict["variant_based_on"] = "Item Attribute"

	# Apply the OR-resolved flags
	local_dict["custom_is_ppb_drug"] = pending[0]
	if bespoke_local:
		local_dict["custom_is_bespoke_drug"] = pending[1]

	# Register any variant attribute values before insert
	for a in local_dict.get("attributes") or []:
		_register_variant_attribute(a.get("attribute"), a.get("attribute_value"))

	# Idempotency: skip if already present
	if frappe.db.exists("Item", item_code):
		return {
			"created": False,
			"item_code": item_code,
			"template_code": template_code,
			"template_created": template_created_flag,
		}

	doc = frappe.get_doc(local_dict)
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.commit()

	return {
		"created": True,
		"item_code": item_code,
		"template_code": template_code,
		"template_created": template_created_flag,
	}


def _create_import_log(
	product_id,
	product_name,
	import_status,
	local_item_code=None,
	local_template_code=None,
	template_created=0,
	strength=None,
	form=None,
	route=None,
	error_message=None,
	source_data=None,
):
	"""Insert a Catalogue Import Log record."""
	log_fields = {
		"doctype": "Catalogue Import Log",
		"product_id": product_id or "",
		"product_name": product_name or "",
		"import_status": import_status,
		"source_api": "PPB",
		"imported_by": frappe.session.user or "Administrator",
		"imported_at": frappe.utils.now(),
	}
	if local_item_code:
		log_fields["local_item_code"] = local_item_code
	if local_template_code:
		log_fields["local_template_code"] = local_template_code
	if template_created:
		log_fields["template_created"] = 1
	if strength:
		log_fields["strength"] = strength
	if form:
		log_fields["form"] = form
	if route:
		log_fields["route"] = route
	if error_message:
		log_fields["error_message"] = error_message
	if source_data:
		log_fields["source_data"] = frappe.as_json(source_data)

	try:
		doc = frappe.get_doc(log_fields)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name
	except Exception:
		frappe.log_error(
			title="Master catalog import: log insert failed",
			message=frappe.get_traceback(),
		)
		return None


def _extract_variant_attributes(item_dict):
	"""Pull strength / form / route strings from the variant's attributes
	child table (or variant_attributes list) for the import log."""
	attrs = {}
	for a in item_dict.get("attributes") or item_dict.get("variant_attributes") or []:
		key = (a.get("attribute") or "").strip()
		val = str(a.get("attribute_value") or "").strip()
		if key and val:
			attrs[key] = val
	return {
		"strength": attrs.get("DRUG STRENGTH"),
		"form": attrs.get("DRUG FORM"),
		"route": attrs.get("Drug Route"),
	}


@frappe.whitelist()
def import_master_item(item_code):
	"""Import a single item (template or variant) from the master catalog
	into the local Item database.

	Catalogue record only — no stock, no Item Price rows.

	:param item_code: the Item name (docname) on the master instance.
	:return: dict with keys:
	          success (bool), status ("imported"|"already_exists"),
	          item_code, template_code, template_created, message
	"""
	if not item_code or not str(item_code).strip():
		frappe.throw("Item code is required.")
	item_code = str(item_code).strip()

	client = _get_master_client()

	# Fetch the full item from master
	remote_doc = client.get_doc("Item", item_code)
	if not remote_doc:
		frappe.throw("Item {0} not found on master.".format(item_code))

	# Check if already exists locally
	if frappe.db.exists("Item", item_code):
		_create_import_log(
			product_id=item_code,
			product_name=remote_doc.get("item_name", item_code),
			import_status="Already Exists",
			local_item_code=item_code,
			local_template_code=(remote_doc.get("variant_of") or "").strip()
			or None,
			template_created=0,
		)
		return {
			"success": True,
			"status": "already_exists",
			"item_code": item_code,
			"template_code": (remote_doc.get("variant_of") or "").strip(),
			"template_created": False,
			"message": "Item {0} already exists locally.".format(item_code),
		}

	# Extract variant attributes for the import log before sanitising
	v_attrs = _extract_variant_attributes(remote_doc)

	try:
		result = _create_local_item(item_code, remote_doc)
	except Exception as e:
		_create_import_log(
			product_id=item_code,
			product_name=remote_doc.get("item_name", item_code),
			import_status="Failed",
			local_item_code=None,
			local_template_code=None,
			template_created=0,
			strength=v_attrs.get("strength"),
			form=v_attrs.get("form"),
			route=v_attrs.get("route"),
			error_message=str(e),
		)
		frappe.throw(
			"Failed to import {0}: {1}".format(item_code, e)
		)

	# Determine if the template was created in this call
	template_code = (remote_doc.get("variant_of") or "").strip()
	template_created = result.get("template_created", False)

	# Re-check: _create_local_item may have set the flag, but it may have
	# created the template and we need to surface that.
	# (template_created is already tracked in the result.)

	_create_import_log(
		product_id=item_code,
		product_name=remote_doc.get("item_name", item_code),
		import_status="Imported",
		local_item_code=item_code,
		local_template_code=template_code or None,
		template_created=1 if template_created else 0,
		strength=v_attrs.get("strength"),
		form=v_attrs.get("form"),
		route=v_attrs.get("route"),
	)

	msg_parts = []
	if template_created:
		msg_parts.append("Template {0} created.".format(template_code))
	msg_parts.append("Item {0} imported.".format(item_code))

	return {
		"success": True,
		"status": "imported",
		"item_code": item_code,
		"template_code": template_code,
		"template_created": template_created,
		"message": " ".join(msg_parts),
	}
