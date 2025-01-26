import frappe
import json

def load_file_data():
    file_name = "loinc.json"  # Change this to your file name
    file_path = frappe.utils.get_site_path("public", "files", file_name)
    # path = "{}/drug_products.json".format(file_path)
    # _file_content = open(file_path)
    # return _file_content
    d = ''
    with open(file_path) as f:
        d = json.load(f)
        # print(d)
    return d


def make_lab_template(template_name):
    data = {
          "name": template_name,
        "lab_test_name": template_name,
            "department": "Nephrology",
            "disabled": 0,
            "link_existing_item": 0,
            "item": template_name,
            "lab_test_code": template_name,
            "lab_test_group": "Services",
            "is_billable": 1,
            "lab_test_rate": 650.0,
            "custom_point_of_care_test": 0,
            "lab_test_description": template_name,
            "lab_test_template_type": "Compound",
            "conversion_factor": 0.0,
            "sensitivity": 0,
            "sample_qty": 0.0,
            "legend_print_position": "Bottom",
            "change_in_item": 0,
            "doctype": "Lab Test Template",
    }