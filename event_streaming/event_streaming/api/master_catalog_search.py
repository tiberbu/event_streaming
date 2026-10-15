# Master-side catalog search endpoints.
#
# This module is installed on the MASTER instance (master.tiberbu.health)
# and is called remotely by other sites via FrappeClient.get_api().
#
# It is safe to import on any Frappe site — the functions simply query
# the local Item database, so on the master instance they search the
# master catalog and on any other site they would search that site.

import frappe


def _bespoke_field_exists() -> bool:
	"""The ``custom_is_bespoke_drug`` Custom Field may not exist on an
	instance that has not yet been deployed with it. Guard every query
	that references the field with this check."""
	return bool(
		frappe.db.exists(
			"Custom Field", {"fieldname": "custom_is_bespoke_drug", "dt": "Item"}
		)
	)


def _drug_query(base_filters: list, bespoke_exists: bool, fields: list, limit: int) -> list:
	"""Run a get_all with the drug-flag OR condition expanded.

	Frappe's filter list has no native OR, so we issue up to two queries
	(PPB and, when the bespoke field is deployed, bespoke) and merge results.
	``base_filters`` should contain only equality/like conditions.
	"""
	filters_ppb = base_filters + [["custom_is_ppb_drug", "=", 1]]
	rows = frappe.get_all("Item", filters=filters_ppb, fields=fields, limit_page_length=limit)
	seen = {r["name"] for r in rows}
	if bespoke_exists:
		filters_bespoke = base_filters + [["custom_is_bespoke_drug", "=", 1]]
		extra = frappe.get_all("Item", filters=filters_bespoke, fields=fields, limit_page_length=limit)
		for r in extra:
			if r["name"] not in seen:
				rows.append(r)
				seen.add(r["name"])
	return rows


def _build_filters(bespoke_exists: bool, like_term: str, **extra) -> list:
	"""Assemble a flat filter list for a get_all call (no drug flag).

	Always includes:
	  - disabled = 0
	  - item_name LIKE %like_term%

	``extra`` provides additional equality conditions as keyword args
	(e.g. ``has_variants=1``).
	"""
	filters = [
		["disabled", "=", 0],
		["item_name", "like", like_term],
	]

	for key, val in extra.items():
		filters.append([key, "=", val])

	return filters


def _row(r, bespoke_exists, is_template=False):
	"""Normalize a raw get_all row into the API response shape."""
	return {
		"item_code": r["name"],
		"item_name": r["item_name"],
		"is_template": is_template,
		"variant_of": r.get("variant_of"),
		"item_group": r.get("item_group", ""),
		"stock_uom": r.get("stock_uom", ""),
		"custom_is_ppb_drug": r.get("custom_is_ppb_drug", 0),
		"custom_is_bespoke_drug": r.get("custom_is_bespoke_drug", 0)
		if bespoke_exists
		else 0,
	}


@frappe.whitelist()
def search_master_items(search_term, limit=20):
	"""Search the master instance's Item doctype for drugs (PPB or bespoke).

	Mirrors the local ``search_drugs_with_variants`` pattern:
	  1. Match templates (has_variants=1) whose name matches the search term
	  2. Match variants directly whose name matches the search term
	  3. For every matched template, fetch ALL its variants

	Only drugs are returned:
	  custom_is_ppb_drug = 1 OR custom_is_bespoke_drug = 1
	(the bespoke half only applies when the Custom Field is deployed).

	No item_group scoping — master is a curated catalog.

	:param search_term: minimum 2 characters, maximum 100.
	:param limit: 1-50 results returned.
	:return: ``{"items": [...], "total": N}``
	"""
	if not search_term or len(search_term.strip()) < 2:
		frappe.throw("Search term must be at least 2 characters.")
	if len(search_term.strip()) > 100:
		frappe.throw("Search term must be at most 100 characters.")

	limit = max(1, min(int(limit), 50))
	search_term = search_term.strip()
	like_term = "%" + search_term + "%"

	bespoke_exists = _bespoke_field_exists()

	field_list = ["name", "item_name", "item_group", "stock_uom", "custom_is_ppb_drug"]
	if bespoke_exists:
		field_list.append("custom_is_bespoke_drug")

	# --- Step 1: templates matching the term ---
	templates = _drug_query(
		_build_filters(bespoke_exists, like_term, has_variants=1),
		bespoke_exists,
		fields=field_list,
		limit=limit,
	)

	# --- Step 2: variants directly matching the term ---
	variant_filters = _build_filters(bespoke_exists, like_term)
	variant_filters.append(["variant_of", "is", "set"])
	matching_variants = _drug_query(
		variant_filters,
		bespoke_exists,
		fields=field_list + ["variant_of"],
		limit=limit,
	)

	# --- Step 3: ALL variants of every matched template ---
	template_codes = sorted({t["name"] for t in templates})
	family_variants = []
	if template_codes:
		family_filters = [
			["disabled", "=", 0],
			["variant_of", "in", template_codes],
		]
		family_variants = _drug_query(
			family_filters,
			bespoke_exists,
			fields=field_list + ["variant_of"],
			limit=limit * 3,
		)

	# --- Merge, dedupe by name, templates first ---
	results = []
	seen = set()

	for t in templates:
		if t["name"] not in seen:
			seen.add(t["name"])
			results.append(_row(t, bespoke_exists, is_template=True))

	for v in matching_variants + family_variants:
		if v["name"] not in seen:
			seen.add(v["name"])
			results.append(_row(v, bespoke_exists))

	return {"items": results[:limit], "total": len(results)}


@frappe.whitelist()
def get_master_item(item_code):
	"""Fetch the full Item document from this instance by item code.

	Used by the dev-site import flow to obtain complete item data including
	the variant ``attributes`` child table.

	:param item_code: the Item name (docname) on this instance.
	:return: full Item dict plus a ``variant_attributes`` list of
	          ``{attribute, attribute_value}`` pairs from the attributes
	          child table.
	"""
	if not item_code:
		frappe.throw("Item code is required.")

	try:
		item = frappe.get_doc("Item", item_code)
	except frappe.DoesNotExistError:
		frappe.throw("Item {0} not found on master.".format(item_code))

	item_dict = item.as_dict()
	item_dict["variant_attributes"] = [
		{"attribute": a.attribute, "attribute_value": a.attribute_value}
		for a in (item.get("attributes") or [])
	]
	return item_dict


# ---------------------------------------------------------------------------
# Master-side Lab Test Template / Clinical Procedure Template search.
# Same pattern as search_master_items: runs on the master instance,
# queries the local database, no Event Producer needed.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def search_master_lab_templates(search_term, limit=20):
	"""Search the master instance's Lab Test Template doctype.

	Identical pattern to ``search_master_items`` — queries the local
	database on the instance where it runs. On master, this searches
	the master catalog.

	:param search_term: minimum 2 characters, maximum 100.
	:param limit: 1-50 results returned.
	:return: ``{"items": [...], "total": N}``
	"""
	if not search_term or len(search_term.strip()) < 2:
		frappe.throw("Search term must be at least 2 characters.")
	if len(search_term.strip()) > 100:
		frappe.throw("Search term must be at most 100 characters.")

	limit = max(1, min(int(limit), 50))
	search_term = search_term.strip().lower()

	rows = frappe.get_all(
		"Lab Test Template",
		filters={"disabled": 0},
		fields=[
			"name",
			"lab_test_name",
			"lab_test_code",
			"item",
			"is_billable",
			"lab_test_template_type",
		],
		limit_page_length=500,
	)

	items = []
	for r in rows:
		name_match = search_term in (r.get("lab_test_name") or "").lower()
		code_match = search_term in (r.get("lab_test_code") or "").lower()
		if name_match or code_match:
			items.append(
				{
					"template_code": r["name"],
					"lab_test_name": r.get("lab_test_name") or r["name"],
					"lab_test_code": r.get("lab_test_code") or "",
					"item": r.get("item") or "",
					"is_billable": r.get("is_billable", 0),
					"lab_test_template_type": r.get("lab_test_template_type") or "",
				}
			)
			if len(items) >= limit:
				break

	return {"items": items, "total": len(items)}


@frappe.whitelist()
def search_master_procedure_templates(search_term, limit=20):
	"""Search the master instance's Clinical Procedure Template doctype.

	Identical pattern to ``search_master_items`` — queries the local
	database on the instance where it runs. On master, this searches
	the master catalog.

	:param search_term: minimum 2 characters, maximum 100.
	:param limit: 1-50 results returned.
	:return: ``{"items": [...], "total": N}``
	"""
	if not search_term or len(search_term.strip()) < 2:
		frappe.throw("Search term must be at least 2 characters.")
	if len(search_term.strip()) > 100:
		frappe.throw("Search term must be at most 100 characters.")

	limit = max(1, min(int(limit), 50))
	search_term = search_term.strip()

	rows = frappe.get_all(
		"Clinical Procedure Template",
		filters={
			"disabled": 0,
			"template": ["like", "%" + search_term + "%"],
		},
		fields=["name", "template", "item", "is_billable", "item_group"],
		limit_page_length=limit,
	)

	items = []
	for r in rows:
		items.append(
			{
				"template_code": r["name"],
				"template_name": r.get("template") or r["name"],
				"item": r.get("item") or "",
				"is_billable": r.get("is_billable", 0),
				"item_group": r.get("item_group") or "",
			}
		)

	return {"items": items, "total": len(items)}
