import frappe
import json

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
                print(name,' ',atc_code,'  ',count)
                create_template(name,'Unit',atc_code)
            if len(item['component_links']) > 1:
                for cp_link in  item['component_links']:
                    try:
                        atc_code = cp_link['component_atc_code']
                        print(name,' ',atc_code,'  ',count)
                        create_template(name,'Unit',atc_code)
                    except:
                        print('err **************************')
                    finally:
                        continue
            count += 1
        except:
            print('ERROR')
        finally:
            continue

def create_terminology_child_table():
    return {}

# bench execute  event_streaming.terminology.drug_templates.create_template

def create_template(item_name='',uom=None,component_atc_code=''):
    # frappe.db.sql("delete from tabItem where name=%s",[item_name])
    data = {
        "item_code": item_name,
        "item_name": item_name,
        "item_group": "Drug",
        "stock_uom": uom or "Nos",
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
            }
             
            
         ],
        'custom_terminology_codes':[
            {
                "terminology": "ATC Code",
                "link": "",
                "code": component_atc_code,
            }
        ]
    }
    doc = frappe.get_doc(data).insert(ignore_permissions=True)
    # terms = doc.append('custom_terminology_codes')
    # terms
    frappe.db.commit()
    print(doc.name)