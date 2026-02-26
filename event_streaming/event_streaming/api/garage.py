
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


# bench execute event_streaming.event_streaming.api.frappe_client_transfers.get_item_variant_attributes
def get_item_variant_attributes():
    doctype = 'Item Variant Attribute'
    producer_url = "https://mombasa.tiberbu.app"

    clients = get_source_and_target_frappe_client_obj(producer_url)
    source_client = clients.get('source_client')
    target_client = clients.get('target_client')
    
    data = target_client.get_list(doctype, fields=['attribute','attribute_value'], limit_page_length=5,filters={'attribute':'Unique Code'})
    print(data)