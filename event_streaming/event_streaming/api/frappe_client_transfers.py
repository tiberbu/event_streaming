
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
def execute_doctype_fetch_and_sync(producer_url='https://master.tiberbu.health',doctype='Item'):
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
                    if item_name in ['Aceclofenac/Paracetamol/']:
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
                                "item_group": remote_item_group,
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
                            "code": row.get("code")
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
    num=0
    # return
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
                parent_data = source_client.get_doc(doctype, name)

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
                parent_data = source_client.get_doc(doctype, name)

                expanded_codes = parent_data.get("expanded_codes", [])
                formatted_codes = [
                    {
                        "code": row.get("code")
                    }
                    for row in expanded_codes
                ]
                update_data["expanded_codes"] = formatted_codes
                
            if doctype == 'Prescription Dosage':
                parent_data = source_client.get_doc(doctype, name)

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
                parent_data = source_client.get_doc(doctype,name)

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
                parent_data = source_client.get_doc(doctype,name)
                
                # item_attribute_values
                attribute_values = parent_data.get("item_attribute_values", [])
                formatted_attribute_values = [
                    {"abbr": attr.get("abbr"),"attribute_value": attr.get("attribute_value")}
                    for attr in attribute_values
                ]
                update_data["item_attribute_values"] = formatted_attribute_values
            # Perform the update
            clean_data = clean_update_data(update_data)
            target_client.update(clean_data)
            print(f"{num} Updated {name} successfully")
            num+=1

        except Exception as e:
            print(f"Failed to update {name}: {e}")

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
def get_sync_status(producer_url='https://hmis.tiberbu.app',doctype='Clinical Procedure Template'):
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


# 'Item Attribute',
# 'Medical Department',
# 'Item Group',
# 'Prescription Dosage',
# 'Dosage Form',
# 'Client Script',
# 'Lab Test UOM',
# 'Concept FormKey Controls',
# 'Dictionary Concept',
# 'Health Program Field Mapping',
# 'Lab Test Template',
# 'Clinical Procedure Template',



def compare_doctype_fields():
    doctype = 'Clinical Procedure Template'
    producer_url = "https://mombasa.tiberbu.app"

    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')

    # Fetch fields from source and target
    source_fields = get_fields(source_client, doctype)
    target_fields = get_fields(target_client, doctype)

    # Convert to sets for easier comparison
    source_fields_set = set(source_fields)
    target_fields_set = set(target_fields)

    # Find differences
    fields_only_in_source = source_fields_set - target_fields_set
    fields_only_in_target = target_fields_set - source_fields_set
    fields_in_both = source_fields_set & target_fields_set

    # Print them
    print(f"\n🔎 Comparison for Doctype: {doctype}")
    print(f"🌍 Source ({source_client.url}):")
    print(f"Fields: {sorted(source_fields)}\n")

    print(f"🏠 Target ({target_client.url}):")
    print(f"Fields: {sorted(target_fields)}\n")

    print(f"✅ Common Fields ({len(fields_in_both)}): {sorted(fields_in_both)}\n")
    print(f"❗ Fields only in Source ({len(fields_only_in_source)}): {sorted(fields_only_in_source)}\n")
    print(f"❗ Fields only in Target ({len(fields_only_in_target)}): {sorted(fields_only_in_target)}\n")

    return {
        "only_in_source": fields_only_in_source,
        "only_in_target": fields_only_in_target,
        "common_fields": fields_in_both
    }

def get_fields(client, doctype):
    meta = client.get_doc("DocType", doctype)
    fields = [d.get('fieldname') for d in meta.get('fields') if d.get('fieldname')]
    fields.append('name')  # Always add 'name' because it's a primary field
    return fields


# bench execute event_streaming.event_streaming.api.frappe_client_transfers.get_item_variant_attributes
def get_item_variant_attributes():
    doctype = 'Item Variant Attribute'
    producer_url = "https://mombasa.tiberbu.app"

    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')
    
    data = target_client.get_list(doctype, fields=['attribute','attribute_value'], limit_page_length=5,filters={'attribute':'Unique Code'})
    print(data)
    
#  bench execute event_streaming.event_streaming.api.frappe_client_transfers.delete_items_by_group
def delete_items_by_group():
    clients = get_source_and_target_frappe_client_obj("https://master.tiberbu.health")
    client = clients.get("target_client")
    groups = [
        "Ace Inhibitors, Combinations",
        "Ace Inhibitors, Plain",
        "Adrenergics For Systemic Use",
        "Adrenergics, Inhalants",
        "Agents Against Amoebiasis And Other Protozoal Diseases",
        "Agents Against Leishmaniasis And Trypanosomiasis",
        "Agents For Treatment Of Hemorrhoids And Anal Fissures For Topical Use",
        "Aldosterone Antagonists And Other Potassium-Sparing Agents",
        "Alkylating Agents",
        "All Other Non-Therapeutic Products",
        "All Other Therapeutic Products",
        "ALPHA-ADRENOCEPTOR BLOCKING DRUGS",
        "Aminoglycoside Antibacterials",
        "Amphenicols",
        "Anabolic Steroids",
        "ANALGESIC/ANTIPYRETIC",
        "ANALGESICS/ DRUGS USED IN RHEUMATIC DISEASES AND GOUT",
        "Androgens",
        "Anesthetics, General",
        "Anesthetics, Local",
        "Angiotensin Ii Receptor Blockers (Arbs), Combinations",
        "Angiotensin Ii Receptor Blockers (Arbs), Plain",
        "Angitotensin Ii Receptor Blockers (Arbs), Plain",
        "Antacids",
        "Anti-Acne Preparations For Systemic Use",
        "Anti-Acne Preparations For Topical Use",
        "Anti-Dementia Drugs",
        "Anti-Inflammatory And Antirheumatic Products, Non-Steroids",
        "Anti-Parathyroid Agents",
        "Antiadrenergic Agents, Centrally Acting",
        "ANTIANGINAL DRUGS",
        "Antiarrhythmics, Class I And Iii",
        "Antibiotics For Topical Use",
        "Anticholinergic Agents",
        "Antidiarrheal Microorganisms",
        "Antiemetics And Antinauseants",
        "Antifibrinolytics",
        "Antifungals For Systemic Use",
        "Antifungals For Topical Use",
        "Antiglaucoma Preparations And Miotics",
        "Antigout Preparations",
        "Antihistamines For Systemic Use",
        "Antiinfectives",
        "Antiinfectives And Antiseptics, Excl. Combinations With Corticosteroids",
        "Antiinfectives/Antiseptics In Combination With Corticosteroids",
        "Antiinflammatory Agents",
        "Antiinflammatory Agents And Antiinfectives In Combination",
        "Antiinflammatory And Antirheumatic Products, Non-Steroids",
        "Antiinflammatory/Antirheumatic Agents In Combination",
        "Antimalarials",
        "Antimetabolites",
        "Antimigraine Preparations",
        "Antimycotics For Systemic Use",
        "Antinematodal Agents",
        "Antiobesity Preparations, Excl. Diet Products",
        "ANTIPLATELET DRUGS",
        "Antipropulsives",
        "Antipruritics, Incl. Antihistamines, Anesthetics, Etc.",
        "Antipsoriatics For Systemic Use",
        "Antipsoriatics For Topical Use",
        "Antipsychotics",
        "Antiseptics And Disinfectants",
        "Antispasmodics In Combination With Analgesics",
        "Antispasmodics In Combination With Psycholeptics",
        "Antithrombotic Agents",
        "Antitrematodals",
        "Antivaricose Therapy",
        "Antivertigo Preparations",
        "Anxiolytics",
        "Appetite Stimulants",
        "Arteriolar Smooth Muscle, Agents Acting On",
        "Ascorbic Acid (Vitamin C), Incl. Combinations"]
    groups2 = [ 
        "Bacterial And Viral Vaccines, Combined",
        "Bacterial Vaccines",
        "Belladonna And Derivatives, Plain",
        "Beta Blocking Agents",
        "Beta Blocking Agents And Other Diuretics",
        "Beta Blocking Agents And Thiazides",
        "Beta Blocking Agents, Other Combinations",
        "BETA-ADRENOCEPTOR BLOCKING DRUGS",
        "Beta-Lactam Antibacterials, Penicillins",
        "Bile Therapy",
        "Blood And Related Products",
        "Blood Glucose Lowering Drugs, Excl. Insulins",
        "Calcium",
        "Calcium Channel Blockers And Diuretics",
        "Capillary Stabilizing Agents",
        "Cardiac Glycosides",
        "Chemotherapeutics For Topical Use",
        "Cicatrizants",
        "Combinations Of Antibacterials",
        "Contraceptives For Topical Use",
        "Corticosteroids",
        "Corticosteroids And Antiinfectives In Combination",
        "Corticosteroids For Systemic Use, Plain",
        "Corticosteroids, Combinations With Antibiotics",
        "Corticosteroids, Combinations With Antiseptics",
        "Corticosteroids, Other Combinations",
        "Corticosteroids, Plain",
        "Cough And Cold Preparations",
        "Cough Suppressants And Expectorants, Combinations",
        "Cough Suppressants, Excl. Combinations With Expectorants",
        "Cytotoxic Antibiotics And Related Substances",
        "Decongestants And Antiallergics",
        "Decongestants And Other Nasal Preparations For Topical Use",
        "Diagnostic Agents",
        "Digestives, Incl. Enzymes",
        "Direct Acting Antivirals",
        "Diuretics And Potassium-Sparing Agents In Combination",
        "Dopaminergic Agents",
        "Drenergics, Inhalants",
        "Drugs Affecting Bone Structure And Mineralization",
        "DRUGS ALL GROUPS,",
        "Drugs For Constipation",
        "DRUGS FOR ERECTILE DYSFUNCTION",
        "Drugs For Functional Gastrointestinal Disorders",
        "Drugs For Peptic Ulcer And Gastro-Oesophageal Reflux Disease (Gord)",
        "Drugs For Peptic Ulcer And Gastro-Oesphageal Reflux Diseas (Gord)",
        "DRUGS FOR THE RELIEF OF SOFT TISSUE INFLAMMATION",
        "Drugs For Treatment Of Lepra",
        "Drugs For Treatment Of Tuberculosis",
        "Drugs Used In Benign Prostatic Hypertrophy",
        "DRUGS USED IN NAUSEA AND VERTIGO",
        "DRUGS USED IN NEUROMUSCULAR DISORDERS",
        "DRUGS USED IN RHEUMATIC DISEASES AND GOUT - NSAID",
        "Ectoparasiticides, Incl. Scabicides",
        "Electrolytes With Carbohydrates",
        "Emollients And Protectives",
        "Enzymes",
        "Estrogens",
        "Expectorants, Excl. Combinations With Cough Suppressants",
        "Gonadotropins And Other Ovulation Stimulants",
        "Herbal",
        "High-Ceiling Diuretics",
        "Hormonal Contraceptives For Systemic Use",
        "Hormone Antagonists And Related Agents",
        "Hormones And Related Agents",
        "Hypnotics And Sedatives",
        "Hypothalamic Hormones",
        "I.V. Solution Additives",
        "I.V. Solutions",
        "Immune Sera",
        "Immunoglobulins",
        "Immunostimulants",
        "Immunosuppressants",
        "Insulin And Analogues",
        "Insulins And Analogues",
        "Intestinal Adsorbents",
        "Intestinal Antiinf+X279Ectives",
        "Intestinal Antiinfectives",
        "Iron Preparations",
        "Irrigating Solutions",
        "Lipid Modifying Agents, Combinations",
        "Lipid Modifying Agents, Plain",
        "LIPID-REGULATING DRUGS",
        "Liver Therapy, Lipotropics",
        "Low-Ceiling Diuretics, Excl, Thiazides",
        "Low-Ceiling Diuretics, Thiazides",
        "Macrolides, Lincosamides And Streptogramins",
        "Magnetic Resonance Imaging Contrast Media",
        "Medicated Dressings",
        "Monoclonal Antibodies And Antibody Drug Conjugates",
        "Multivitamins, Combinations",
        "Multivitamins, Plain",
        "Muscle Relaxants, Centrally Acting Agents",
        "Muscle Relaxants, Peripherally Acting Agents",
        "Mydriatics And Cycloplegics",
        "Nasal Decongestants For Systemic Use",
        "None",
        "NUTRITION",
        "Ocular Vascular Disorder Agents",
        "Opioids",
        "Orticosteroids For Systemic Use, Plain",
        "Other Alimentary Tract And Metabolism Products",
        "Other Analgesics And Antipyretics",
        "Other Antianemic Preparations",
        "Other Antibacterials",
        "Other Antidiarrheals",
        "Other Antihypertensives",
        "Other Antineoplastic Agents",
        "Other Beta-Lactam Antibacterials",
        "Other Cardiac Preparations",
        "Other Cold Preparations",
        "Other Dermatological Preparations",
        "Other Diagnostic Agents",
        "Other Drugs For Acid Related Disorders",
        "Other Drugs For Disorders Of The Musculo-Skeletal System",
        "Other Drugs For Obstructive Airway Diseases, Inhalants",
        "Other Drugs Used In Diabetes",
        "Other Gynecologicals",
        "Other Mineral Supplements",
        "Other Nutrients",
        "Other Ophthalmologicals",
        "Other Otologicals",
        "Other Plain Vitamin Preparations",
        "Other Respiratory System Products",
        "Other Sex Hormones And Modulators Of The Genital System",
        "Other Systemic Drugs For Obstructive Airway Diseases",
        "Other Vaccines",
        "Other Vitamin Products, Combinations",
        "Parasympathomimetics",
        "Peripheral Vasodilators",
        "Plant Alkaloids And Other Natural Products",
        "Posterior Pituitary Lobe Hormones",
        "Potassium",
        "Progestogens",
        "Progestogens And Estrogens In Combination",
        "Propulsives",
        "Protein Kinase Inhibitors",
        "Psychostimulants, Agents Used For Adhd And Nootropics",
        "Quinolone Antibacterials",
        "Respiratory System",
        "Selective Calcium Channel Blockers With Direct Cardiac Effects",
        "Selective Calcium Channel Blockers With Mainly Vascular Effects",
        "Stomatological Preparations",
        "Sulfonamides And Trimethoprim",
        "Surgical Aids",
        "Tetracyclines",
        "Throat Preparations",
        "Thyroid Preparations",
        "Topical Products For Joint And Muscular Pain",
        "Urologicals",
        "Uterotonics",
        "Vasodilators Used In Cardiac Diseases",
        "Viral Vaccines",
        "Vitamin A And D, Incl. Combinations Of The Two",
        "Vitamin B-Complex, Incl. Combinations",
        "Vitamin B1, Plain And In Combination With Vitamin B6 And B12",
        "Vitamin B12 And Folic Acid",
        "Vitamin K And Other Hemostatics",
        "X-Ray Contrast Media, Iodinated"
        ]


    try:
        filters = [["item_group", "in", groups]]
        # items = client.get_list("Item", filters=filters, fields=["name"],limit_page_length=5)
        items = client.get_list(
            "Item",
            filters=filters,
            fields=["name"],
            limit_page_length=500,   # number of records to fetch
            limit_start=0          # optional offset
        )

        print(f"Found {len(items)} items in groups {groups}")

        for item in items:
            name = item.get("name")
            try:
                client.delete("Item", name)
                print(f"✅ Deleted Item: {name}")
            except Exception as e:
                print(f"❌ Failed to delete {name}: {e}")

        print("🎯 Done deleting selected items.")

    except Exception as e:
        print(f"⚠️ Error deleting items: {e}")
