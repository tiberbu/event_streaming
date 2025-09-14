
import frappe
from frappe.utils.background_jobs import enqueue, get_jobs


# bench execute event_streaming.event_streaming.api.garage.append_queue_state_movements_to_queue
def append_queue_state_movements_to_queue():
    from .frappe_client_transfers import get_source_and_target_frappe_client_obj
    doctype = 'Queue State'
    producer_url = "https://master.tiberbu.health"
    clients = get_source_and_target_frappe_client_obj(producer_url)
    target_client = clients.get('target_client')
    
    data = target_client.get_list(doctype, fields=['name','creation','company'], limit_page_length=10000,
                                  filters={
                                    'creation': ['between', ['2025-07-15 00:00:00', '2025-07-15 23:59:59']]
                                    }
                                  )
    count = 0
    for item in data:
        try:
            parent = target_client.get_doc(doctype, item.get('name'))
            child_row = {
                'healthcare_service_unit': parent.get('healthcare_service_unit'),
                'service_point': parent.get('service_point'),
                'signed_off': 1,
                'is_revisit': None,
            }
            
            appointment_data = target_client.get_list(
                "Patient Appointment", 
                filters={"name": parent.get('appointment')}, 
                fields=["custom_is_revisit"],
                limit_page_length=1
            )
            if appointment_data:
                child_row['is_revisit'] = appointment_data[0].get('custom_is_revisit')
            
            # Initialize child table if it doesn't exist
            if 'table_gedu' not in parent:
                parent['table_gedu'] = []
            
            # Append to the child table list
            parent['table_gedu'].append(child_row)
            
            # Save the document
            target_client.update(parent)
            
            print(f"{count}✓ Saved {item.get('name')}: {child_row}")
            count += 1
            
        except Exception as e:
            print(f"✗ Error processing {item.get('name')}: {e}")
    
    print(f"Successfully processed {count} records")