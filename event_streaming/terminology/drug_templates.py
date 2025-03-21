import frappe
import json
from frappe.deferred_insert import deferred_insert as _deferred_insert

def load_file_data():
    file_name = "active_ingredients.json"  # Change this to your file name
    file_path = frappe.utils.get_site_path("public", "files", file_name)
    # path = "{}/drug_products.json".format(file_path)
    # _file_content = open(file_path)
    # return _file_content
    d = ''
    with open(file_path) as f:
        d = json.load(f)
        # print(d)
    return d
# bench execute event_streaming
# bench execute  event_streaming.terminology.drug_templates.parse_message
@frappe.whitelist()
def parse_message():
    count = 0
    for item in load_file_data().get('Data').get('ac'):
        try:
            # if count < 10:
            name = item['component_description']
            if len(item['component_links']) == 1:
                atc_code = item['component_links'][0]['component_atc_code']
                # print(name,' ',atc_code,'  ',count)
                create_template(name,'Unit',atc_code)
            if len(item['component_links']) > 1:
                for cp_link in  item['component_links']:
                    try:
                        atc_code = cp_link['component_atc_code'] or cp_link['active_component_id']
                        # print(name,' ',atc_code,'  ',count)
                        active_component_id = cp_link['active_component_id']
                        # print(name,' ---->  ',active_component_id)
                        create_template(name,'Unit',atc_code)
                    except:
                        print('err **************************')
                    finally:
                        continue
            count += 1
        except Exception as e:
            exception_message = str(e)
            create_error_log(exception_message, item['component_description'])
        finally:
            continue

def create_error_log(err,item):
    data =  [{
            "method": 'parse_message for {0}'.format(item),
            "error": err,
            # "doctype": "Error Log"
        }]
    _deferred_insert("Error Log", data)

def create_terminology_child_table():
    return {}

# bench execute  event_streaming.terminology.drug_templates.create_template

def create_template(item_name='',uom=None,component_atc_code=''):
    # frappe.db.sql("delete from tabItem where name=%s",[item_name])
    # append_active_component(component_atc_code)
    data = {
        "item_code": item_name,
        "item_name": item_name,
        "item_group": "Drug",
        # "stock_uom": uom or "Nos",
        "custom_is_one_off_drug": 0,
        "disabled": 0,
        "allow_alternative_item": 0,
        "is_stock_item": 1,
        "has_variants": 1,
        "end_of_life": "2099-12-31",
        "default_material_request_type": "Purchase",
        "variant_based_on": "Item Attribute",
        "has_expiry_date": 0,
        "is_sales_item": 1,
        "doctype": "Item",
        "has_batch_no": 1,
        "create_new_batch": 1,
        "has_expiry_date": 1,
         "attributes": [
            {
                "attribute": "DRUG STRENGTH",
                "numeric_values": 0,
                "disabled": 1,
                "from_range": 0.0,
                "increment": 0.0,
                "to_range": 0.0,
            }, 
            {
                "attribute": "Brand Name",
                "numeric_values": 0,
                "disabled": 1,
                "from_range": 0.0,
                "increment": 0.0,
                "to_range": 0.0,
            },
             {
                "attribute": 'DRUG FORM',
                "numeric_values": 0,
                "disabled": 1,
                "from_range": 0.0,
                "increment": 0.0,
                "to_range": 0.0,
            },
            {
                "attribute": 'Drug Route',
                "numeric_values": 0,
                "disabled": 1,
                "from_range": 0.0,
                "increment": 0.0,
                "to_range": 0.0,
            },
            #    {
            #     "attribute": 'ATC Code',
            #     "numeric_values": 0,
            #     "disabled": 1,
            #     "from_range": 0.0,
            #     "increment": 0.0,
            #     "to_range": 0.0,
            # }
             
            
         ],
        'custom_terminology_codes':[
            {
                "terminology": "ATC Code",
                "link": "",
                "code": component_atc_code,
            }
        ]
    }
    if not frappe.db.exists('Item',{'name':item_name}):
        doc = frappe.get_doc(data).insert(ignore_permissions=True)
        frappe.db.commit()
        print(doc.name)
    
def append_active_component(val):
    if not frappe.db.exists('Item Attribute Value',{'parent': 'ATC Code','attribute_value':str(val)}):
        doc = frappe.get_doc('Item Attribute', 'ATC Code')
        itm = doc.append('item_attribute_values')
        itm.attribute_value  = str(val)
        itm.abbr = str(val)
        doc.save()
        frappe.db.commit()

def get_tpl_code(item_name):
    # "custom_terminology_codes": [
    #             {
    #                 "terminology": "ATC Code",
    #                 "link": "",
    #                 "code": "85308430",
    #                 "parent": "mouthwash",
    #                 "parentfield": "custom_terminology_codes",
    #                 "parenttype": "Item",
    #                 "doctype": "Terminology Codes"
    #             }
    #         ],
    return frappe.db.get_value('Terminology Codes',{ "parent": item_name, "parentfield": "custom_terminology_codes","parenttype": "Item"},'code') or item_name
# bench execute  event_streaming.terminology.drug_templates.return_item_from_uat

@frappe.whitelist(allow_guest=1)
def return_item_from_uat():
    items = frappe.db.sql("select name,stock_uom from tabItem where is_stock_item=1 and has_variants=1 and disabled=0 order by rand() limit 2 ",as_dict=1)
    results = []
    for item in items:
        results.append({'code':get_tpl_code(item.name),'item':item.name})
    return results

# bench execute  event_streaming.terminology.drug_templates.import_item_from_uat
 
@frappe.whitelist()
def import_item_from_uat():
    import requests
    base_url = 'https://mombasa-uat.tiberbu.app/api/method/'
    # base_url2 = 'https://hmis.tiberbu.app/api/method/'
    uat_link = '{0}event_streaming.terminology.drug_templates.return_item_from_uat'.format(base_url)
    try:
        # print(response.json())
        response = requests.get(uat_link,headers={})
        for item in response.json()['message']:
            try:
                print(item)
                create_item_fom_uat(item_name=item['item'],uom=None,component_atc_code=item['code'])
            except Exception as e:
                exception_message = str(e)
                create_error_log(exception_message, item['item'])
    except Exception as e:
        exception_message = str(e)
        create_error_log(exception_message, 'import_item_from_uat')

    
@frappe.whitelist()
def create_item_fom_uat(item_name='',uom=None,component_atc_code=''):
    create_template(item_name,uom,component_atc_code)