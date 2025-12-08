import frappe
from ..crons.setup import create_missing_item_groups, set_item_allow_rename_attribute

def on_event_producer_creation(doc,status):
    create_missing_item_groups()
    set_item_allow_rename_attribute()