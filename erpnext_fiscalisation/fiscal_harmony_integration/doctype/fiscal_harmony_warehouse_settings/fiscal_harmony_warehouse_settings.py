# Copyright (c) 2025, Eskill Trading (Pvt) Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from erpnext_fiscalisation.fiscal_harmony_integration.utils import FiscalHarmonyBase

class FiscalHarmonyWarehouseSettings(Document, FiscalHarmonyBase):
    def validate(self):
        """Validate the Fiscal Harmony Warehouse Settings form data."""
        import re
        url_regex = r"^https://[a-z]+\.([a-z]+\.)*(co\.zw|com)/[a-z]+$"
        if not re.match(url_regex, self.endpoint):
            frappe.throw("Please enter a valid URL for the endpoint, then try again.")

    @frappe.whitelist()
    def check_supported_currencies(self):
        """Display a list of currency codes supported by Fiscal Harmony."""
        response = self.make_request("/currencymapping/supported-currencies")
        if not response.ok:
            frappe.throw(f"{response.status_code}: {response.reason}")

        message = "Supported currencies are:<br/><ul>"
        currency_list = response.text.strip(r"[]").replace('"', "").split(r",")
        for currency in currency_list:
            message += f"<li>{currency}</li>"
        message += "</ul>"
        frappe.msgprint(message)

    @frappe.whitelist()
    def check_user_profile(self):
        """Updates the Fiscal Harmony user profile."""
        response = self.make_request("/profile")
        if not response.ok:
            frappe.throw("Unable to verify user profile.")

        data = response.json()
        self.user_profile_id = data.get("Id", "")
        self.save()
        frappe.msgprint("User profile fetched and updated.")

    @frappe.whitelist()
    def validate_currency_mappings(self):
        """Validate the currency mappings."""
        self.process_mappings(
            "currency",
            {
                "SourceCurrency": "system_currency",
                "DestinationCurrency": "fiscal_harmony_currency",
            },
        )

    @frappe.whitelist()
    def validate_tax_mappings(self):
        """Validate the tax mappings."""
        self.process_mappings(
            "tax",
            {
                "TaxCode": "tax_code",
                "DestinationTaxId": "destination_tax_id",
            },
        )

    @frappe.whitelist()
    def validate_api_details(self, api_key: str, api_secret: str):
        """Validate the provided API details, and submit them if they are correct."""

        headers = self.get_headers(api_key)

        try:
            import requests
            response = requests.get(
                self.get_request_url("/fiscaldevice"),
                headers=headers,
                timeout=30,
            )
        except (TimeoutError, requests.exceptions.Timeout):
            frappe.throw(
                "Fiscal Harmony took too long to respond. Please try again later."
            )

        if not response.ok:
            match response.status_code:
                case 401:
                    frappe.throw("Failed to authenticate. Please check API details.")
                case 404:
                    frappe.throw(
                        "Unable to locate service, please check endpoint address."
                    )
                case _:
                    if response.status_code >= 500:
                        frappe.throw("The revenue authority is unavailable.")
                    frappe.throw(
                        "Failed to authenticate. Please check provided details."
                    )

        self.update_last_successful_request()
        self.api_key = api_key
        self.api_secret = api_secret
        self.save()

        frappe.msgprint(
            "Successfully validated and stored the provided API details.",
            "Authentication Validated",
        )
