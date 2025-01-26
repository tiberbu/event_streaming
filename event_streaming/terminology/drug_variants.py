import frappe
import json

# bench execute  event_streaming.terminology.drug_variants.load_file_data
def load_file_data():
    file_name = "products.json"  # Change this to your file name
    file_path = frappe.utils.get_site_path("public", "files", file_name)
    # path = "{}/drug_products.json".format(file_path)
    # _file_content = open(file_path)
    # return _file_content
    d = ''
    with open(file_path) as f:
        d = json.load(f)
        # print(d)
    return d

# bench execute  event_streaming.terminology.drug_variants.create_variant_loop
@frappe.whitelist()
def create_variant_loop():
    count = 0
    message = load_file_data()
    # print(message)
    errors=[]
    for item in message.get('Data').get('products'):
        product_id = item.get('product_id')
        try:
            if not frappe.db.exists('Item',{'name':product_id}):
                name = item.get('brand_display_name')
                template_name=item.get('generic_name')
                # atc_code = item['component_links'][0]['component_atc_code']
                ppb_registration_code = item.get('ppb_registration_code')
                knhts_concept_id = item.get('knhts_concept_id')
                form_description = item.get('form_description')
                strength_amount = item.get('strength_amount')
                append_strength(strength_amount)
                print('inserted ' ,name,' ',product_id,'  ',count,' ',strength_amount)
                desc = "{0}".format(strength_amount)
                brand = item.get('brand_name')
                append_to_brand_name(brand)
                form_name = item.get('form_description')
                append_to_form(form_name)
                route = item.get('route_description')
                append_drug_route(route)
                create_variant(name,template_name,ppb_registration_code,knhts_concept_id,product_id,desc,strength_amount,brand,form_name,route)
                count += 1
            else:
                print('already inserted ',product_id)
        except:
            errors.append(product_id)
            print('err ',product_id)
            # # except :
            #     # print('ERROR')
        finally:
            frappe.db.commit()
            continue
# def extract_digits(test_string):
#     numbers = []
#     for char in test_string:
#         if char.isdigit():
#             numbers.append(int(char))
#     # return numbers[0]

# print("The numbers list is:", numbers)
def update_variant_attribute(template,attribute):
    template_doc = frappe.get_doc('Item',template)
    
def create_variant(item_code,variant_of,ppb_registration_code,knhts_concept_id,product_id,desc,strength_amount,brand,form_name,route):
    template_uom = frappe.get_cached_value('Item',variant_of,'stock_uom')
    data={
        "item_code": str(product_id),
        "item_name":  item_code,
        "item_group": "Drug",
        "stock_uom": template_uom,#"Unit",
        "custom_is_one_off_drug": 0,
        "disabled": 0,
        "allow_alternative_item": 0,
        "is_stock_item": 1,
        "has_variants": 0,
        "is_sales_item": 1,
        "shelf_life_in_days": 0,
        "end_of_life": "2099-12-31",
        "default_material_request_type": "Purchase",
        "variant_of": variant_of,
        "description":desc,
        "variant_based_on": "Item Attribute",
        "doctype": "Item", 
        "attributes": [
            {
                 "variant_of": variant_of,
                    "attribute": "DRUG STRENGTH",
                    "attribute_value": r"{0}".format(strength_amount),# extract_digits(),#"100",
                    "numeric_values": 0,
                    "disabled": 1,
                    "from_range": 0.0,
                    "increment": 0.0,
                    "to_range": 0.0,
            },
              {
                 "variant_of": variant_of,
                    "attribute": "Brand Name",
                    "attribute_value": brand,# extract_digits(),#"100",
                    "numeric_values": 0,
                    "disabled": 1,
                    "from_range": 0.0,
                    "increment": 0.0,
                    "to_range": 0.0,
            },
            {
                 "variant_of": variant_of,
                    "attribute": "DRUG FORM",
                    "attribute_value": form_name,# extract_digits(),#"100",
                    "numeric_values": 0,
                    "disabled": 1,
                    "from_range": 0.0,
                    "increment": 0.0,
                    "to_range": 0.0,
            },
             {
                 "variant_of": variant_of,
                "attribute": 'Drug Route',
                "attribute_value": route,# extract_digits(),#"100",
                "numeric_values": 0,
                "disabled": 1,
                "from_range": 0.0,
                "increment": 0.0,
                "to_range": 0.0,
            },
            
         ],
        'custom_terminology_codes':[
        {
            "terminology": "Pharmacy and Poisons Board",
            "link": "",
            "code": ppb_registration_code or '-'
        },
            {
            "terminology": "KNHTS Concept",
            "link": "",
            "code": knhts_concept_id or '-'
        }
    ]
    }
    # print(data)
    doc = frappe.get_doc(data).insert()
    # doc.db_insert()
    print('insert completed ',doc.name)
    frappe.db.commit()
    
def append_to_brand_name(val):
    # print(str(val).replace("/",'-'),' ****************************************')
    if not frappe.db.exists('Item Attribute Value',{'parent':'Brand Name','attribute_value':str(val)}):
        doc = frappe.get_doc('Item Attribute','Brand Name')
        itm = doc.append('item_attribute_values')
        itm.attribute_value  = str(val)
        itm.abbr = str(val)
        doc.save()
        
def append_to_form(val):
    # print(str(val).replace("/",'-'),' ****************************************')
    if not frappe.db.exists('Item Attribute Value',{'parent':'DRUG FORM','attribute_value':str(val)}):
        doc = frappe.get_doc('Item Attribute','DRUG FORM')
        itm = doc.append('item_attribute_values')
        itm.attribute_value  = str(val)
        itm.abbr = str(val)
        doc.save()
        
def append_drug_route(val):
    if not frappe.db.exists('Item Attribute Value',{'parent': 'Drug Route','attribute_value':str(val)}):
        doc = frappe.get_doc('Item Attribute', 'Drug Route')
        itm = doc.append('item_attribute_values')
        itm.attribute_value  = str(val)
        itm.abbr = str(val)
        doc.save()
        
def append_strength(val):
    if not frappe.db.exists('Item Attribute Value',{'parent': 'DRUG STRENGTH','attribute_value':str(val)}):
        doc = frappe.get_doc('Item Attribute', 'DRUG STRENGTH')
        itm = doc.append('item_attribute_values')
        itm.attribute_value  = str(val)
        itm.abbr = str(val)
        doc.save()