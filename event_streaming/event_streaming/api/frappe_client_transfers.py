
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
def execute_doctype_fetch_and_sync(producer_url='https://master.tiberbu.health',doctype='Labs And Procedures Items'):
    insert_non_existing_records(producer_url,doctype)
    # enqueue(method=insert_non_existing_records, queue='long', timeout=3600, producer_url=producer_url,doctype=doctype)


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
    target_filters.pop("disabled", None)

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
                # .replace("\r", "").replace("\n", " ").strip()
                print(num, item_name)
                
                data = {
                    "doctype": doctype,
                    "docname": item_name
                }
                for field in fields:
                    data[field] = document.get(field)
                # add attribute child table to item
                if doctype == 'Item':
                    if item_name in ['IBUPROFEN','Ibuprofen SUSPENSION-60ml','Aceclofenac/Paracetamol/','ALBENDAZOLE','METRONIDAZOLE','ATORVASTATIN CALCIUM','CHLORAMPHENICOL']:
                        print(f"Skipping problematic Item: {item_name}")
                        continue
                    
                    parent_data = source_client.get_doc(doctype, item_name)
                    # formatted_ic = parent_data.get('item_code') + ' '  + parent_data.get('item_group')
                    # print('formatted_ic  ',formatted_ic)
                    # data['item_code'] = formatted_ic
                    # attributes
                    attributes = parent_data.get("attributes", [])
                    formatted_attributes = [
                        {"attribute": attr.get("attribute"), "attribute_value": attr.get("attribute_value")}
                        for attr in attributes
                    ]

                    # uoms
                    uoms = parent_data.get("uoms", [])
                    formatted_uoms = [
                        {"uom": uom.get("uom"), "conversion_factor": uom.get("conversion_factor")}
                        for uom in uoms
                    ]

                    # custom_terminology_codes
                    terminology_codes = parent_data.get("custom_terminology_codes", [])
                    formatted_terminology_codes = [
                        {"terminology": code.get("terminology"),"link":code.get("link"), "code": code.get("code")}
                        for code in terminology_codes
                    ]

                #     formatted_attributes.append( {
                #     "attribute": 'Unique Code',
                #     "numeric_values": 0,
                #     "attribute_value":''.join(random.choices(string.ascii_uppercase + string.digits, k=5)),
                #     "disabled": 0,
                #     "from_range": 0.0,
                #     "increment": 0.0,
                #     "to_range": 0.0,
                # })
                    data["attributes"] = formatted_attributes
                    data["uoms"] = formatted_uoms
                    data["custom_terminology_codes"] = formatted_terminology_codes
                    # data.pop('custom_benefits_exchange_code')
                    # del data['custom_benefits_exchange_code']

                    

                # add terminology codes childtable
                if doctype == 'Clinical Procedure Template':
                    data['link_existing_item'] = 1
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # check if item exists then create it
                    remote_item = parent_data.get('item')
                    remote_item_group = parent_data.get('item_group')
                    

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
                                "is_stock_item":0,
                            })

                            
                    # custom_terminology_codes
                    terminology_codes = parent_data.get("custom_terminology_codes", [])
                    formatted_terminology_codes = [
                        {"terminology": code.get("terminology"),"link":code.get("link"), "code": code.get("code")}
                        for code in terminology_codes
                    ]

                    # codification_table
                    codifications = parent_data.get("codification_table", [])
                    formatted_codifications = [
                        {"code": code.get("code"),"code_system":code.get("code_system"), "code_value": code.get("code_value"),
                         "definition": code.get("definition"),"system": code.get("system"),"oid": code.get("oid")}
                        for code in codifications
                    ]

                    # custom_pre_auth_configuration
                    pre_auth_configurations = parent_data.get("custom_pre_auth_configuration", [])
                    formatted_pre_auth_configurations = [
                        {"facility_level": code.get("facility_level"),"requires_pre_auth":code.get("requires_pre_auth"), "scheme": code.get("scheme")}
                        for code in pre_auth_configurations
                    ]

                    # custom_interventions_configuration
                    interventions_configuration = parent_data.get("custom_interventions_configuration", [])
                    formatted_interventions_configuration = [
                        {"intervention_code": code.get("intervention_code"),"sha_intervention":code.get("sha_intervention"),
                         "speciality_intervention": code.get("speciality_intervention"),"speciality_intervention_type": code.get("speciality_intervention_type")}
                        for code in interventions_configuration
                    ]

                    data["custom_terminology_codes"] = formatted_terminology_codes
                    data["codification_table"] = formatted_codifications
                    data["custom_pre_auth_configuration"] = formatted_pre_auth_configurations
                    data["custom_interventions_configuration"] = formatted_interventions_configuration

                if doctype == 'Lab Test Template':
                    data['link_existing_item'] = 1
                    parent_data = source_client.get_doc(doctype, document.get("name"))
                    
                    # check if item exists then create it
                    remote_item = parent_data.get('item')
                    remote_item_group = parent_data.get('item_group')
                    

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
                                "is_stock_item":0,
                            })

                    # custom_terminology_codes
                    terminology_codes = parent_data.get("custom_terminology_codes", [])
                    formatted_terminology_codes = [
                        {"terminology": code.get("terminology"),"link":code.get("link"), "code": code.get("code")}
                        for code in terminology_codes
                    ]

                    # codification_table
                    codifications = parent_data.get("codification_table", [])
                    formatted_codifications = [
                        {"code": code.get("code"),"code_system":code.get("code_system"), "code_value": code.get("code_value"),
                         "definition": code.get("definition"),"system": code.get("system"),"oid": code.get("oid")}
                        for code in codifications
                    ]

                    # normal_test_templates
                    test_templates = parent_data.get("normal_test_templates", [])
                    formatted_normal_test_templates = [
                        {"lab_test_event": template.get("lab_test_event"),"lab_test_uom": template.get("lab_test_uom"),
                         "normal_range":template.get("normal_range"),"custom_dictionary_concept":template.get("custom_dictionary_concept"), "secondary_uom": template.get("secondary_uom"),
                         "allow_blank": template.get("allow_blank"),"conversion_factor": template.get("conversion_factor")}
                        for template in test_templates
                    ]

                    # descriptive_test_templates
                    desc_test_templates = parent_data.get("descriptive_test_templates", [])
                    formatted_descriptive_test_templates = [
                        {"particulars": template.get("particulars"),
                         "allow_blank": template.get("allow_blank")}
                        for template in desc_test_templates
                    ]

                    # custom_items
                    c_items = parent_data.get("custom_items", [])
                    formatted_custom_items = [
                        {"actual_qty": item.get("actual_qty"),"barcode": item.get("barcode"),"batch_no": item.get("batch_no"),
                         "conversion_factor": item.get("conversion_factor"),"invoice_separately_as_consumables": item.get("invoice_separately_as_consumables"),
                         "item_code": item.get("item_code"),"item_name": item.get("item_name"),
                         "qty": item.get("qty"),"stock_uom": item.get("stock_uom"),
                         "transfer_qty": item.get("transfer_qty"),"uom": item.get("uom")}
                        for item in c_items
                    ]

                    # custom_results_implications
                    results_implications = parent_data.get("custom_results_implications", [])
                    formatted_results_implications = [
                        {"lab_results_implications": implication.get("lab_results_implications")}
                        for implication in results_implications]

                    data["custom_terminology_codes"] = formatted_terminology_codes
                    data["codification_table"] = formatted_codifications
                    data["normal_test_templates"] = formatted_normal_test_templates
                    data["descriptive_test_templates"] = formatted_descriptive_test_templates
                    data["custom_items"] = formatted_custom_items
                    data["custom_results_implications"] = formatted_results_implications

                if doctype == 'Item Attribute':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # item_attribute_values
                    attribute_values = parent_data.get("item_attribute_values", [])
                    formatted_attribute_values = [
                        {"abbr": attr.get("abbr"),"attribute_value": attr.get("attribute_value")}
                        for attr in attribute_values
                    ]
                    data["item_attribute_values"] = formatted_attribute_values

                if doctype == 'SHA Intervention':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # payment_mechanism
                    payment_mechanisms = parent_data.get("payment_mechanism", [])
                    formatted_payment_mechanisms = [
                        {"payment_mode": mech.get("payment_mode"),"is_civil_servant": mech.get("is_civil_servant")}
                        for mech in payment_mechanisms
                    ]
                    data["payment_mechanism"] = formatted_payment_mechanisms

                if doctype == 'Role Profile':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # roles
                    roles = parent_data.get("roles", [])
                    formatted_roles = [
                        {"role": role.get("role")}
                        for role in roles
                    ]
                    data["roles"] = formatted_roles

                if doctype == 'Workflow':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # states
                    states = parent_data.get("states", [])
                    formatted_states = [
                        {"allow_edit": state.get("allow_edit"),"avoid_status_override": state.get("avoid_status_override"),
                         "doc_status": state.get("doc_status"),"docstatus": state.get("docstatus"),
                         "send_email": state.get("send_email"),"state": state.get("state")}
                        for state in states
                    ]
                    data["states"] = formatted_states

                    # transitions
                    transitions = parent_data.get("transitions", [])
                    formatted_transitions = [
                        {
                            "action": transition.get("action"),
                            "allow_self_approval": transition.get("allow_self_approval"),
                            "allowed": transition.get("allowed"),
                            "docstatus": transition.get("docstatus"),
                            "next_state": transition.get("next_state"),
                            "send_email_to_creator": transition.get("send_email_to_creator"),
                            "state": transition.get("state"),
                        }
                        for transition in transitions
                    ]
                    data["transitions"] = formatted_transitions
                
                if doctype == 'Health Program Workflow':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # workflow_state_transitions
                    transitions = parent_data.get("workflow_state_transitions", [])
                    formatted_transitions = [
                        {"entry_point": transition.get("entry_point"),"state": transition.get("state"),
                        "next_state": transition.get("next_state")}
                        for transition in transitions
                    ]
                    data["workflow_state_transitions"] = formatted_transitions

                if doctype == 'Description Reports Mapping':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    # table_multiselect_gavr (ICD11 Multiselect)
                    icd11_multiselect = parent_data.get("table_multiselect_gavr", [])
                    formatted_icd11_multiselect = [
                        {
                            "icd11_explanation": row.get("icd11_explanation")
                        }
                        for row in icd11_multiselect
                    ]

                    # clinical_procedure_template
                    clinical_procedures = parent_data.get("clinical_procedure_template", [])
                    formatted_clinical_procedures = [
                        {
                            "clinical_procedure_template": row.get("clinical_procedure_template")
                        }
                        for row in clinical_procedures
                    ]

                    # xray_and_imaging
                    imaging_procedures = parent_data.get("xray_and_imaging", [])
                    formatted_imaging_procedures = [
                        {
                            "clinical_procedure_template": row.get("clinical_procedure_template")
                        }
                        for row in imaging_procedures
                    ]

                    # table_gtuk (labs)
                    lab_tests = parent_data.get("table_gtuk", [])
                    formatted_lab_tests = [
                        {
                            "lab_test_template": row.get("lab_test_template")
                        }
                        for row in lab_tests
                    ]

                    # table_itgx (special clinics)
                    special_clinics = parent_data.get("table_itgx", [])
                    formatted_special_clinics = [
                        {
                            "facility": row.get("facility"),
                            "service_unit": row.get("service_unit")
                        }
                        for row in special_clinics
                    ]

                    # forms
                    form_templates = parent_data.get("forms", [])
                    formatted_form_templates = [
                        {
                            "form_dictionary_concept": row.get("form_dictionary_concept")
                        }
                        for row in form_templates
                    ]

                    data["table_multiselect_gavr"] = formatted_icd11_multiselect
                    data["clinical_procedure_template"] = formatted_clinical_procedures
                    data["xray_and_imaging"] = formatted_imaging_procedures
                    data["table_gtuk"] = formatted_lab_tests
                    data["table_itgx"] = formatted_special_clinics
                    data["forms"] = formatted_form_templates

                if doctype == 'ICD11 Collection':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    expanded_codes = parent_data.get("expanded_codes", [])
                    formatted_codes = [
                        {
                            "code": row.get("code"),
                            "description": row.get("description")
                        }
                        for row in expanded_codes
                    ]
                    data["expanded_codes"] = formatted_codes
                    
                if doctype == 'Prescription Dosage':
                    parent_data = source_client.get_doc(doctype, document.get("name"))

                    expanded_codes = parent_data.get("dosage_strength", [])
                    formatted_codes = [
                        {
                            "strength": row.get("strength"),
                            "strength_time": row.get("strength_time"),
                        }
                        for row in expanded_codes
                    ]
                    data["dosage_strength"] = formatted_codes
                

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
                    # args = {}
                    # for i, d in enumerate(data['attributes']):
                    #     d['idx']= i + 1
                    #     args[d['attribute']] = d['attribute_value']

                    # variant = get_variant(data['variant_of'], args, data['item_code'])
                    # if not variant:
                    target_client.insert_many(docs_to_insert)
                    print(f"{len(docs_to_insert)} documents successfully inserted.")
                except Exception as insert_exception:
                    frappe.throw(f"Insert failed: {insert_exception}")
                    # print(f"Insert failed: {insert_exception}")
                # finally:
                #     continue

            limit_start += batch_size
        

    except Exception as e:
        frappe.throw(f"An error occurred: {e}")

# bench execute event_streaming.event_streaming.api.frappe_client_transfers.update_existing_records
@frappe.whitelist()
def update_existing_records(producer_url='https://master.tiberbu.health',doctype='Item'):
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
    
    target_filters = filters.copy()
    target_filters.pop("creation", None)
    target_filters.pop("disabled", None)

    source_list = source_client.get_list(doctype, fields=["name"], limit_page_length=50000, filters=filters)
    target_list = target_client.get_list(doctype, fields=["name"], limit_page_length=50000, filters=target_filters)

    source_names = {item["name"] for item in source_list}
    target_names = {item["name"] for item in target_list}

    common_names = sorted(source_names & target_names)
    total = len(common_names)
    print(f"{total} records found in both source and target to update")

    # --- Modified-based filtering (commented out for now, update all records instead) ---
    # source_list = source_client.get_list(doctype, fields=["name", "modified"], limit_page_length=50000, filters=filters)
    # target_list = target_client.get_list(doctype, fields=["name", "modified"], limit_page_length=50000, filters=filters)
    # source_map = {item["name"]: item["modified"] for item in source_list}
    # target_map = {item["name"]: item["modified"] for item in target_list}
    # common_names = sorted([
    #     name for name in source_map
    #     if name in target_map and str(source_map[name]) > str(target_map[name])
    # ])
    # total = len(common_names)
    # all_common = len(set(source_map) & set(target_map))
    # print(f"{all_common} records in both, {total} modified on master since last sync")

    # Check for an existing "Running" progress doc to resume from
    existing = frappe.get_all(
        "Data Sync Progress",
        filters={"document_type": doctype, "status": "Running"},
        order_by="creation desc",
        limit_page_length=1
    )

    if existing:
        progress = frappe.get_doc("Data Sync Progress", existing[0].name)
        progress.processed = int(progress.processed or 0)
        progress.success = int(progress.success or 0)
        progress.failed = int(progress.failed or 0)
        skip = progress.processed
        common_names = common_names[skip:]
        print(f"Resuming from record {skip}, {len(common_names)} remaining")
    else:
        progress = frappe.get_doc({
            "doctype": "Data Sync Progress",
            "document_type": doctype,
            "total_records": total,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "status": "Running",
            "synced_at": None
        })
        progress.insert(ignore_permissions=True)
        frappe.db.commit()

    num=0
    for name in common_names:
        try:
            source_doc = source_client.get_doc(doctype, name)
            update_data = {
                "doctype": doctype,
                "name": name,
            }

            for field in fields:
                update_data[field] = source_doc.get(field)


            if doctype == 'Lab Test Template':
                parent_data = source_doc

                # custom_terminology_codes
                terminology_codes = parent_data.get("custom_terminology_codes", [])
                formatted_terminology_codes = [
                    {"terminology": code.get("terminology"),"link":code.get("link"), "code": code.get("code")}
                    for code in terminology_codes
                ]

                # codification_table
                codifications = parent_data.get("codification_table", [])
                formatted_codifications = [
                    {"code": code.get("code"),"code_system":code.get("code_system"), "code_value": code.get("code_value"),
                        "definition": code.get("definition"),"system": code.get("system"),"oid": code.get("oid")}
                    for code in codifications
                ]

                # normal_test_templates
                test_templates = parent_data.get("normal_test_templates", [])
                formatted_normal_test_templates = [
                    {"lab_test_event": template.get("lab_test_event"),"lab_test_uom": template.get("lab_test_uom"),
                        "normal_range":template.get("normal_range"),"custom_dictionary_concept":template.get("custom_dictionary_concept"),"secondary_uom": template.get("secondary_uom"),
                        "allow_blank": template.get("allow_blank"),"conversion_factor": template.get("conversion_factor")}
                    for template in test_templates
                ]

                # descriptive_test_templates
                desc_test_templates = parent_data.get("descriptive_test_templates", [])
                formatted_descriptive_test_templates = [
                    {"particulars": template.get("particulars"),
                        "allow_blank": template.get("allow_blank")}
                    for template in desc_test_templates
                ]

                # custom_items
                c_items = parent_data.get("custom_items", [])
                formatted_custom_items = [
                    {"actual_qty": item.get("actual_qty"),"barcode": item.get("barcode"),"batch_no": item.get("batch_no"),
                        "conversion_factor": item.get("conversion_factor"),"invoice_separately_as_consumables": item.get("invoice_separately_as_consumables"),
                        "item_code": item.get("item_code"),"item_name": item.get("item_name"),
                        "qty": item.get("qty"),"stock_uom": item.get("stock_uom"),
                        "transfer_qty": item.get("transfer_qty"),"uom": item.get("uom")}
                    for item in c_items
                ]

                # custom_results_implications
                results_implications = parent_data.get("custom_results_implications", [])
                formatted_results_implications = [
                    {"lab_results_implications": implication.get("lab_results_implications")}
                    for implication in results_implications]

                update_data["custom_terminology_codes"] = formatted_terminology_codes
                update_data["codification_table"] = formatted_codifications
                update_data["normal_test_templates"] = formatted_normal_test_templates
                update_data["descriptive_test_templates"] = formatted_descriptive_test_templates
                update_data["custom_items"] = formatted_custom_items
                update_data["custom_results_implications"] = formatted_results_implications

            if doctype == 'ICD11 Collection':
                parent_data = source_doc

                expanded_codes = parent_data.get("expanded_codes", [])
                formatted_codes = [
                    {
                        "code": row.get("code")
                    }
                    for row in expanded_codes
                ]
                update_data["expanded_codes"] = formatted_codes
                
            if doctype == 'Prescription Dosage':
                parent_data = source_doc

                expanded_codes = parent_data.get("dosage_strength", [])
                formatted_codes = [
                    {
                        "strength": row.get("strength"),
                        "strength_time": row.get("strength_time"),
                    }
                    for row in expanded_codes
                ]
                update_data["dosage_strength"] = formatted_codes

            if doctype == 'Description Reports Mapping':
                parent_data = source_doc

                # table_multiselect_gavr (ICD11 Multiselect)
                icd11_multiselect = parent_data.get("table_multiselect_gavr", [])
                formatted_icd11_multiselect = [
                    {
                        "icd11_explanation": row.get("icd11_explanation")
                    }
                    for row in icd11_multiselect
                ]

                # clinical_procedure_template
                clinical_procedures = parent_data.get("clinical_procedure_template", [])
                formatted_clinical_procedures = [
                    {
                        "clinical_procedure_template": row.get("clinical_procedure_template")
                    }
                    for row in clinical_procedures
                ]

                # xray_and_imaging
                imaging_procedures = parent_data.get("xray_and_imaging", [])
                formatted_imaging_procedures = [
                    {
                        "clinical_procedure_template": row.get("clinical_procedure_template")
                    }
                    for row in imaging_procedures
                ]

                # table_gtuk (labs)
                lab_tests = parent_data.get("table_gtuk", [])
                formatted_lab_tests = [
                    {
                        "lab_test_template": row.get("lab_test_template")
                    }
                    for row in lab_tests
                ]

                # table_itgx (special clinics)
                special_clinics = parent_data.get("table_itgx", [])
                formatted_special_clinics = [
                    {
                        "facility": row.get("facility"),
                        "service_unit": row.get("service_unit")
                    }
                    for row in special_clinics
                ]

                # forms
                form_templates = parent_data.get("forms", [])
                formatted_form_templates = [
                    {
                        "form_dictionary_concept": row.get("form_dictionary_concept")
                    }
                    for row in form_templates
                ]

                update_data["table_multiselect_gavr"] = formatted_icd11_multiselect
                update_data["clinical_procedure_template"] = formatted_clinical_procedures
                update_data["xray_and_imaging"] = formatted_imaging_procedures
                update_data["table_gtuk"] = formatted_lab_tests
                update_data["table_itgx"] = formatted_special_clinics
                update_data["forms"] = formatted_form_templates
            
            if doctype == 'Item Attribute':
                parent_data = source_doc

                # item_attribute_values
                attribute_values = parent_data.get("item_attribute_values", [])
                formatted_attribute_values = [
                    {"abbr": attr.get("abbr"),"attribute_value": attr.get("attribute_value")}
                    for attr in attribute_values
                ]
                update_data["item_attribute_values"] = formatted_attribute_values

            if doctype == 'Item':
                parent_data = source_doc

                # attributes
                attributes = parent_data.get("attributes", [])
                formatted_attributes = [
                    {"attribute": attr.get("attribute"), "attribute_value": attr.get("attribute_value")}
                    for attr in attributes
                ]

                # uoms
                uoms = parent_data.get("uoms", [])
                formatted_uoms = [
                    {"uom": uom.get("uom"), "conversion_factor": uom.get("conversion_factor")}
                    for uom in uoms
                ]

                # custom_terminology_codes
                terminology_codes = parent_data.get("custom_terminology_codes", [])
                formatted_terminology_codes = [
                    {"terminology": code.get("terminology"),"link":code.get("link"), "code": code.get("code")}
                    for code in terminology_codes
                ]

                update_data["attributes"] = formatted_attributes
                update_data["uoms"] = formatted_uoms
                update_data["custom_terminology_codes"] = formatted_terminology_codes

            if doctype == 'Clinical Procedure Template':
                parent_data = source_doc

                # custom_terminology_codes
                terminology_codes = parent_data.get("custom_terminology_codes", [])
                formatted_terminology_codes = [
                    {"terminology": code.get("terminology"),"link":code.get("link"), "code": code.get("code")}
                    for code in terminology_codes
                ]

                # codification_table
                codifications = parent_data.get("codification_table", [])
                formatted_codifications = [
                    {"code": code.get("code"),"code_system":code.get("code_system"), "code_value": code.get("code_value"),
                     "definition": code.get("definition"),"system": code.get("system"),"oid": code.get("oid")}
                    for code in codifications
                ]

                # custom_pre_auth_configuration
                pre_auth_configurations = parent_data.get("custom_pre_auth_configuration", [])
                formatted_pre_auth_configurations = [
                    {"facility_level": code.get("facility_level"),"requires_pre_auth":code.get("requires_pre_auth"), "scheme": code.get("scheme")}
                    for code in pre_auth_configurations
                ]

                # custom_interventions_configuration
                interventions_configuration = parent_data.get("custom_interventions_configuration", [])
                formatted_interventions_configuration = [
                    {"intervention_code": code.get("intervention_code"),"sha_intervention":code.get("sha_intervention"),
                     "speciality_intervention": code.get("speciality_intervention"),"speciality_intervention_type": code.get("speciality_intervention_type")}
                    for code in interventions_configuration
                ]

                update_data["custom_terminology_codes"] = formatted_terminology_codes
                update_data["codification_table"] = formatted_codifications
                update_data["custom_pre_auth_configuration"] = formatted_pre_auth_configurations
                update_data["custom_interventions_configuration"] = formatted_interventions_configuration

            if doctype == 'SHA Intervention':
                parent_data = source_doc

                # payment_mechanism
                payment_mechanisms = parent_data.get("payment_mechanism", [])
                formatted_payment_mechanisms = [
                    {"payment_mode": mech.get("payment_mode"),"is_civil_servant": mech.get("is_civil_servant")}
                    for mech in payment_mechanisms
                ]
                update_data["payment_mechanism"] = formatted_payment_mechanisms

            if doctype == 'Role Profile':
                parent_data = source_doc

                # roles
                roles = parent_data.get("roles", [])
                formatted_roles = [
                    {"role": role.get("role")}
                    for role in roles
                ]
                update_data["roles"] = formatted_roles

            if doctype == 'Workflow':
                parent_data = source_doc

                # states
                states = parent_data.get("states", [])
                formatted_states = [
                    {"allow_edit": state.get("allow_edit"),"avoid_status_override": state.get("avoid_status_override"),
                     "doc_status": state.get("doc_status"),"docstatus": state.get("docstatus"),
                     "send_email": state.get("send_email"),"state": state.get("state")}
                    for state in states
                ]
                update_data["states"] = formatted_states

                # transitions
                transitions = parent_data.get("transitions", [])
                formatted_transitions = [
                    {
                        "action": transition.get("action"),
                        "allow_self_approval": transition.get("allow_self_approval"),
                        "allowed": transition.get("allowed"),
                        "docstatus": transition.get("docstatus"),
                        "next_state": transition.get("next_state"),
                        "send_email_to_creator": transition.get("send_email_to_creator"),
                        "state": transition.get("state"),
                    }
                    for transition in transitions
                ]
                update_data["transitions"] = formatted_transitions

            if doctype == 'Health Program Workflow':
                parent_data = source_doc

                # workflow_state_transitions
                transitions = parent_data.get("workflow_state_transitions", [])
                formatted_transitions = [
                    {"entry_point": transition.get("entry_point"),"state": transition.get("state"),
                    "next_state": transition.get("next_state")}
                    for transition in transitions
                ]
                update_data["workflow_state_transitions"] = formatted_transitions

            # Perform the update
            clean_data = clean_update_data(update_data)
            target_client.update(clean_data)
            num+=1
            print(f"{num}/{len(common_names)} Updated {name} successfully")

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

# bench execute event_streaming.event_streaming.api.frappe_client_transfers.update_item_names
@frappe.whitelist()
def update_item_names(producer_url='https://master.tiberbu.health', doctype='Item'):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get("source_client")
    target_client = clients.get("target_client")

    filters = {}
    if doctype == 'Item Alternative':
        doctype = "Item"
        filters = {"is_stock_item": 1, "has_variants": 1, "custom_is_ppb_drug": 1, "disabled": 0}
    elif doctype == 'Item':
        filters = {"is_stock_item": 1, "has_variants": 0, "custom_is_ppb_drug": 1, "disabled": 0}
    elif doctype == 'Labs And Procedures Items':
        doctype = "Item"
        filters = {"is_stock_item": 0, "disabled": 0}

    source_list = source_client.get_list("Item", fields=["name", "item_name"], limit_page_length=50000, filters=filters)
    target_list = target_client.get_list("Item", fields=["name"], limit_page_length=50000, filters=filters)

    source_map = {item["name"]: item["item_name"] for item in source_list}
    target_names = {item["name"] for item in target_list}

    to_update = sorted(name for name in source_map if name in target_names)
    total = len(to_update)
    print(f"{total} common items to update item_name")

    # Resume support
    existing = frappe.get_all(
        "Data Sync Progress",
        filters={"document_type": doctype, "status": "Running"},
        order_by="creation desc",
        limit_page_length=1
    )

    if existing:
        progress = frappe.get_doc("Data Sync Progress", existing[0].name)
        progress.processed = int(progress.processed or 0)
        progress.success = int(progress.success or 0)
        progress.failed = int(progress.failed or 0)
        skip = progress.processed
        to_update = to_update[skip:]
        print(f"Resuming from record {skip}, {len(to_update)} remaining")
    else:
        progress = frappe.get_doc({
            "doctype": "Data Sync Progress",
            "document_type": doctype,
            "total_records": total,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "status": "Running",
            "synced_at": None
        })
        progress.insert(ignore_permissions=True)
        frappe.db.commit()

    num = 0
    for name in to_update:
        try:
            target_client.update({
                "doctype": "Item",
                "name": name,
                "item_name": source_map[name],
            })
            num += 1
            print(f"{num}/{len(to_update)} Updated item_name for {name}")
            progress.success += 1
        except Exception as e:
            print(f"Failed to update {name}: {e}")
            progress.failed += 1
        finally:
            progress.processed += 1
            progress.save(ignore_permissions=True)
            frappe.db.commit()

    progress.synced_at = frappe.utils.now()
    progress.status = "Completed"
    progress.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Done. {num}/{len(to_update)} item names updated.")


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
    source_client = FrappeClient(producer_url, api_key=producer_doc.api_key, api_secret='c71e20c68d96e14')
    target_client = FrappeClient(get_host_name(), api_key=get_user_api_key(producer_doc.user).get('api_key'), api_secret=get_user_api_key(producer_doc.user).get('api_secret'))
    return {'source_client':source_client,'target_client':target_client}


# bench execute hmis.hmis.setup.frappe-client.get_user_api_key
def get_user_api_key(user):
    user = frappe.get_doc("User", user)
    if not user.api_key or not user.api_secret:
        return {"error": "API key or secret does not exist for this user."}
        
    return {'api_key':'57480720296d13e','api_secret':'5dc09f8628deb44'}#nairobi
    # return {'api_key':"618d952c6dc3e1c",'api_secret':'c1805b5785ac91d'} #elgeyo
    return {'api_key':"f9513f6d1363e7a",'api_secret':'a0fc7e676baeae7'} #kericho

    return {"api_key": user.api_key, "api_secret": user.get_password('api_secret')}

def get_host_name():
    site_config = frappe.local.conf
    host_name = site_config.get('hostname', 'default_host_name')    
    
    return 'https://nairobi.tiberbu.app'

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
    target_client = clients.get('target_client')

    source_count = len(source_client.get_list(
        doctype_query,
        fields=["name"],
        filters=filters,
        limit_page_length=50000
    ))

    target_count = len(target_client.get_list(
        doctype_query,
        fields=["name"],
        filters=target_filters,
        limit_page_length=50000
    ))

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
