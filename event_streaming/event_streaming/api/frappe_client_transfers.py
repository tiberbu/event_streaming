
from frappe.frappeclient import FrappeClient
import frappe
from frappe.utils.data import now 
from frappe.utils.background_jobs import enqueue


source_client = None
target_client = None

# bench execute event_streaming.event_streaming.api.frappe_client_transfers.execute_doctype_fetch_and_sync Clinical Procedure Template
@frappe.whitelist()
def execute_doctype_fetch_and_sync(producer_url='https://master.tiberbu.health',doctype='Clinical Procedure Template'):
    # insert_non_existing_records(producer_url,doctype)
    enqueue(method=insert_non_existing_records, queue='long', timeout=3600, producer_url=producer_url,doctype=doctype)


# bench execute hmis.hmis.setup.utility_frappe_client.insert_non_existing_records  filters={"creation": [">", '2024-10-30 11:18:43.421245']} filters={'name': ['like', '%physical%']} Health Program Field Mapping
def insert_non_existing_records(producer_url,doctype="Item"):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')

    filters={}
    if doctype == 'Item Alternative':
        doctype = "Item"
        filters = {'has_variants':1,'disabled':0}
    elif doctype == 'Item':
        filters = {'has_variants':0,'disabled':0}

    fields = get_doctype_fields(doctype)


    list1 = target_client.get_list(doctype, fields=fields, limit_page_length=50000,filters=filters)
    list2 = source_client.get_list(doctype, fields=fields, limit_page_length=50000,filters=filters)
    
    
    target_names = {item['name'] for item in list1}
    source_names = {item['name'] for item in list2}

    items_in_source_not_in_target = source_names - target_names
    print(len(source_names))
    print(len(target_names))
    print(doctype," Items Missing In Source:",len(items_in_source_not_in_target))
    # return
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
                         "normal_range":template.get("normal_range"), "secondary_uom": template.get("secondary_uom"),
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

                    data["custom_terminology_codes"] = formatted_terminology_codes
                    data["codification_table"] = formatted_codifications
                    data["normal_test_templates"] = formatted_normal_test_templates
                    data["descriptive_test_templates"] = formatted_descriptive_test_templates
                    data["custom_items"] = formatted_custom_items

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

                
                print('add to insert')
                docs_to_insert.append(data)

            if docs_to_insert:
                print("Beginning bulk insert")
                try:
                    target_client.insert_many(docs_to_insert)
                    print(f"{len(docs_to_insert)} documents successfully inserted.")
                except Exception as insert_exception:
                    frappe.throw(f"Insert failed: {insert_exception}")

            limit_start += batch_size
        

    except Exception as e:
        frappe.throw(f"An error occurred: {e}")



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
        filters = {'has_variants':1,'disabled':0}
    elif doctype == 'Item':
        filters = {'has_variants':0,'disabled':0}

    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')

    source_count = len(source_client.get_list(doctype, fields=["name"],filters=filters,limit_page_length=50000))
    target_count = len(target_client.get_list(doctype, fields=["name"],filters=filters,limit_page_length=50000))
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