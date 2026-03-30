# Copyright (c) 2025, Eskill Trading (Pvt) Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from erpnext_fiscalisation.fiscal_harmony_integration.utils import FiscalHarmonyBase

class FiscalHarmonyWarehouseAPICredential(Document, FiscalHarmonyBase):
    def get_password(self, fieldname):
        return frappe.utils.password.get_decrypted_password(self.doctype, self.name, fieldname)
