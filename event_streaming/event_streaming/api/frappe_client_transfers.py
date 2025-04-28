
from frappe.frappeclient import FrappeClient
import frappe
from frappe.utils.data import now 

source_client = None
target_client = None

# bench execute event_streaming.event_streaming.api.frappe_client_transfers.execute_doctype_fetch_and_sync
@frappe.whitelist()
def execute_doctype_fetch_and_sync(producer_url='https://mombasa.tiberbu.app',doctype='Dictionary Concept'):
    insert_non_existing_records(producer_url,doctype)


# bench execute hmis.hmis.setup.utility_frappe_client.insert_non_existing_records  filters={"creation": [">", '2024-10-30 11:18:43.421245']} filters={'name': ['like', '%physical%']} Health Program Field Mapping
def insert_non_existing_records(producer_url,doctype="Item"):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')


    fields = get_doctype_fields(doctype)
    
    list1 = target_client.get_list(doctype, fields=fields, limit_page_length=50000)
    list2 = source_client.get_list(doctype, fields=fields, limit_page_length=50000)
    
    
    target_names = {item['name'] for item in list1}
    source_names = {item['name'] for item in list2}

    items_in_source_not_in_target = source_names - target_names
    print(doctype," Items Missing In Source:",len(items_in_source_not_in_target))
    # return
    try:
        batch_size = 1
        limit_start = 0
        num = 0
        while True:
            documents_batch = [item for item in list2 if item['name'] in items_in_source_not_in_target][limit_start:limit_start + batch_size]

            if not documents_batch: 
                break

            docs_to_insert = []

            for document in documents_batch:
                num += 1
                print(num, document.get('name'))

                data = {
                    "doctype": doctype,
                    "docname": document.get('name')  
                }
                for field in fields:
                    data[field] = document.get(field)

                if doctype == 'Item':
                    parent_data = source_client.get_doc("Item", document.get("name"))
                    attributes = parent_data.get("attributes", [])
                    formatted_attributes = [
                        {"attribute": attr.get("attribute"), "attribute_value": attr.get("attribute_value")}
                        for attr in attributes
                    ]
                    data["attributes"] = formatted_attributes
                
                if doctype == 'Clinical Procedure Template':
                    data['link_existing_item'] = 1
                
                if document.get('name', '') not in ['Flucloxacclinxxx','0']:
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


# bench execute hmis.hmis.setup.frappe-client.get_doctype_fields
def get_doctype_fields(doctype_name='Healthcare Service Unit Type'):
    meta = frappe.get_meta(doctype_name)
    field_list = [
            field.fieldname
            for field in meta.fields
            if field.fieldtype not in ["Column Break", "Section Break", "HTML", "Button", "Read Only", 
            "Fold", "Tab Break", "Image", "Geolocation", "Color"]
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



# bench execute hmis.hmis.setup.frappe-client.get_sync_status
@frappe.whitelist()
def get_sync_status(producer_url='https://mombasa.tiberbu.app',doctype='Item'):
    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')

    source_count = len(source_client.get_list(doctype, fields=["name"],limit_page_length=50000))
    target_count = len(target_client.get_list(doctype, fields=["name"],limit_page_length=50000))
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
