# Copyright (c) 2024, Eskill Trading (Pvt) Ltd and contributors
# For license information, please see license.txt

# pylint: disable=not-an-iterable

import base64
from datetime import datetime
import hashlib
import hmac
import json
import re
from typing import TYPE_CHECKING

import requests

import frappe
from frappe.model.document import Document

from erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_log.fiscal_harmony_log import (
    fh_log,
    FiscalHarmonyLogData,
)

if TYPE_CHECKING:
    from frappe.types import DF
    from erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_signature.fiscal_signature import (
        FiscalSignature,
    )


@frappe.whitelist()
def switch_active_company(target_company: str):
    doc = frappe.get_doc("Fiscal Harmony Settings")  # Load singleton
    return doc.switch_active_company(target_company)


@frappe.whitelist()
def get_device_info():
    doc = frappe.get_single("Fiscal Harmony Settings")  # Singleton
    return doc.get_device_info()


@frappe.whitelist()
def check_user_profile():
    doc = frappe.get_doc("Fiscal Harmony Settings")
    return doc.check_user_profile


@frappe.whitelist()
def update_multi_company_details():
    doc = frappe.get_doc("Fiscal Harmony Settings")
    return doc.update_multi_company_details


@frappe.whitelist()
def validate_api_details(api_key, api_secret):
    doc = frappe.get_doc("Fiscal Harmony Settings")
    return doc.validate_api_details(api_key, api_secret)


class FiscalHarmonySettings(Document):
    """This doctype manages interactions with the Fiscal Harmony API."""

    __ERROR_TITLE = "Fiscal Harmony Error"
    __TIMEOUT = 30
    """Default timeout for requests."""

    if TYPE_CHECKING:
        endpoint: DF.Data
        user_profile_id: DF.Data
        api_key: DF.Data
        api_secret: DF.Password
        last_successful_request: DF.Datetime
        currency_mappings: DF.Table
        tax_mappings: DF.Table

    def validate(self):
        """Validate the Fiscal Harmony Settings form data."""

        url_regex = r"^https://[a-z]+\.([a-z]+\.)*(co\.zw|com)/[a-z]+$"

        if not re.match(url_regex, self.endpoint):
            frappe.throw("Please enter a valid URL for the endpoint, then try again.")

    @frappe.whitelist()
    def check_supported_currencies(self):
        """Display a list of currency codes supported by Fiscal Harmony."""

        response = self.__make_request("/currencymapping/supported-currencies")
        if not response.ok:
            frappe.throw(f"{response.status_code}: {response.reason}")

        message = "Supported currencies are:<br/><ul>"
        currency_list = response.text.strip(r"[]").replace('"', "").split(r",")
        for currency in currency_list:
            message += f"<li>{currency}</li>"
        message += "</ul>"

        frappe.msgprint(message)

    def check_user_profile(self):
        """Updates the Fiscal Harmony user profile."""

        response = self.__make_request("/profile")

        if not response.ok:
            frappe.throw(
                "Unable to verify user profile.",
                title=FiscalHarmonySettings.__ERROR_TITLE,
            )

        else:
            frappe.msgprint(
                "User profile fetched and updated.",
                title="Fiscal Harmony: Check User Profile",
            )

        data = response.json()
        self.user_profile_id = data.get("Id", "")
        self.save()

    def download_fiscal_pdf(self, signature: "FiscalSignature") -> bytes | None:
        """Download the fiscal PDF listed on the signature and attach to the invoice.

        Args:
            signature (FiscalSignature): The document that stores the fiscal result.

        Returns:
            bytes|None: Returns the content of the downloaded PDF."""

        if not signature.fiscal_harmony_filename:
            frappe.log_error(
                "Fiscal Harmony: PDF Error",
                f"No PDF available for signature {signature.name}.",
            )
            return None

        request_url = self.__get_request_url(
            f"/download/{signature.fiscal_harmony_filename}"
        )
        headers = self.__get_headers()
        log_data: FiscalHarmonyLogData = {
            "request_url": request_url,
        }

        try:
            response = requests.get(
                request_url,
                headers=headers,
                timeout=FiscalHarmonySettings.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            log_data["response"] = str(response.content)
            response.raise_for_status()

            log_data["status"] = "Success"
            self.__update_last_successful_request()

        except TimeoutError:
            log_data["status"] = "Failure"
            log_data["error_details"] = ""
            log_data["response_status_code"] = 500
            fh_log(log_data)
            frappe.throw("The connection timed out.")

        except requests.exceptions.HTTPError:
            log_data["error_details"] = response.reason
            if response.status_code == 401:
                log_data["status"] = "Unauthorised"
            else:
                log_data["status"] = "Failure"

        fh_log(log_data)

        return response.content

    def fetch_signature_data(self, signature: "FiscalSignature"):
        """Fetches the data of an already fiscalised signature that did not have its data returned\
            via webhook.

        Args:
            signature (FiscalSignature): The document that stores the fiscal result."""

        if not signature.fiscal_harmony_id or signature.fdms_url:
            return

        url = self.__get_request_url("status")
        data = [str(signature.fiscal_harmony_id)]
        log_data: FiscalHarmonyLogData = {
            "request_url": url,
            "payload": json.dumps(data, indent=2),
        }
        payload = self.__encode_data(data)
        headers = self.__get_signed_headers(payload)

        try:
            response = requests.post(
                url,
                data=payload,
                headers=headers,
                timeout=FiscalHarmonySettings.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            log_data["response"] = json.dumps(response.json(), indent=2)

            response.raise_for_status()

            response_data = response.json()[0]
            signature.is_retry = (
                    not response_data["Success"] and response_data["IsActionable"]
            )
            if response_data["Error"]:
                signature.error = response_data["Error"]
            elif signature.error:
                signature.error = ""

            if qr_data := response_data["QrData"]:
                signature.fdms_url = qr_data["QrCodeUrl"]
                signature.verification_code = qr_data["VerificationCode"]
                signature.fiscal_day = qr_data["FiscalDay"]
                signature.device_id = qr_data["DeviceId"]
                signature.invoice_number = qr_data["InvoiceNumber"]

            signature.fiscal_harmony_filename = response_data.get(
                "FiscalInvoicePdf",
                None,
            )

            log_data["status"] = "Success"
            self.__update_last_successful_request()

        except TimeoutError:
            signature.is_retry = True
            log_data["status"] = "Failure"
            log_data["error_details"] = (
                f"Timed out whilst signing {signature.sales_invoice}."
            )
            log_data["response_status_code"] = 500

        except requests.exceptions.HTTPError:
            signature.is_retry = True
            log_data["error_details"] = (
                f"{response.reason} whilst signing {signature.sales_invoice}."
            )
            match response.status_code:
                case 400:
                    log_data["status"] = "Invalid JSON"
                case 401:
                    log_data["status"] = "Unauthorised"
                    log_data["signature_valid"] = False
                case _:
                    log_data["status"] = "Failure"

        finally:
            signature.save(ignore_permissions=True)
            fh_log(log_data)

            if signature.fiscal_harmony_filename:
                signature.download_or_generate_pdf()

    def fiscalise_transaction(self, signature: "FiscalSignature"):
        """Fiscalises the invoice/credit note attached to the given signature.

        Args:
            signature (FiscalSignature): The document that stores the fiscal result."""

        data = signature.get_payload_data()
        payload = self.__encode_data(data)
        headers = self.__get_signed_headers(payload)
        url = self.__get_request_url(
            "creditnote" if "CreditNoteId" in data else "invoice"
        )
        log_data: FiscalHarmonyLogData = {
            "request_url": url,
            "payload": json.dumps(data, indent=2),
        }
        if signature.is_retry:
            signature.is_retry = False

        try:
            response = requests.post(
                url,
                data=payload,
                headers=headers,
                timeout=FiscalHarmonySettings.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            try:
                log_data["response"] = json.dumps(response.json(), indent=2)
            except json.JSONDecodeError:
                log_data["response"] = response.text

            response.raise_for_status()

            signature.fiscal_harmony_id = response.text
            log_data["status"] = "Success"
            self.__update_last_successful_request()

        except TimeoutError:
            signature.is_retry = True
            log_data["status"] = "Failure"
            log_data["error_details"] = (
                f"Timed out whilst signing {signature.sales_invoice}."
            )
            log_data["response_status_code"] = 500

        except requests.exceptions.HTTPError:
            signature.is_retry = True
            log_data["error_details"] = (
                f"{response.reason} whilst signing {signature.sales_invoice}."
            )
            match response.status_code:
                case 400:
                    log_data["status"] = "Invalid JSON"
                case 401:
                    log_data["status"] = "Unauthorised"
                    log_data["signature_valid"] = False
                case _:
                    log_data["status"] = "Failure"

        finally:
            signature.save(ignore_permissions=True)
            fh_log(log_data)

    def get_device_info(self):
        """Displays the Fiscal Harmony fiscal device config to the user."""

        response = self.__make_request("/fiscaldevice")
        if not response.ok:
            frappe.throw(
                "Failed to fetch the device status.",
                title=FiscalHarmonySettings.__ERROR_TITLE,
            )

        def print_value(key: str, value: str, indent: int = 0) -> str:
            if (
                    isinstance(value, str)
                    and value.startswith(r"{")
                    and value.endswith(r"}")
            ):
                value = json.loads(value)

            message = f'<strong style="margin-left: {indent}rem">{key}</strong>:'
            if isinstance(value, dict):
                message += "<br/>"
                for inner_key, inner_value in value.items():
                    message += print_value(inner_key, inner_value, indent + 1)

            elif isinstance(value, list):
                message += '<br/><ol style="margin-bottom: 0">'
                for item in value:
                    message += f"<li>{print_value(key, item, indent + 1)}</li>"
                message += "</ol>"

            else:
                message += f" {value}<br/>"

            return message

        message = ""
        for key, value in response.json().items():
            message += print_value(key, value)

        frappe.msgprint(message, "Fiscal Device Info")

    def test_signature(self, received_signature: str, raw_data: str) -> bool:
        """Validate that the received signature is correct for the data received.

        Args:
            received_signature (str): The signature included in the headers of the received request.
            raw_data (str): The body of the received request.

        Returns:
            bool: Whether the received signature is valid."""

        expected_signature = self.__sign_payload(raw_data)

        return received_signature == expected_signature

    def validate_api_details(self, api_key: str, api_secret: str):
        """Validate the provided API details, and submit them if they are correct.

        Args:
            api_key (str): The API Key to authenticate with Fiscal Harmony.
            api_secret (str): The API Secret to authenticate with Fiscal Harmony."""

        headers = self.__get_headers(api_key)

        try:
            response = requests.get(
                self.__get_request_url("/fiscaldevice"),
                headers=headers,
                timeout=FiscalHarmonySettings.__TIMEOUT,
            )
        except TimeoutError:
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

        self.__update_last_successful_request()
        self.api_key = api_key
        self.api_secret = api_secret
        self.save()

        frappe.msgprint(
            "Successfully validated and stored the provided API details.",
            "Authentication Validated",
        )

    @frappe.whitelist()
    def validate_currency_mappings(self):
        """Validate the currency mappings."""

        self.__process_mappings(
            "currency",
            {
                "SourceCurrency": "system_currency",
                "DestinationCurrency": "fiscal_harmony_currency",
            },
        )

    @frappe.whitelist()
    def validate_tax_mappings(self):
        """Validate the tax mappings."""

        self.__process_mappings(
            "tax",
            {
                "TaxCode": "tax_code",
                "DestinationTaxId": "destination_tax_id",
            },
        )

    # Add these fields to your TYPE_CHECKING section:
    if TYPE_CHECKING:
        endpoint: DF.Data
        user_profile_id: DF.Data
        api_key: DF.Data
        api_secret: DF.Password
        last_successful_request: DF.Datetime
        currency_mappings: DF.Table
        tax_mappings: DF.Table
        # New fields for multi-company support
        multiple_companies: DF.Check
        company_1_name: DF.Data
        company_1_api_key: DF.Data
        company_1_api_secret: DF.Password
        company_2_name: DF.Data
        company_2_api_key: DF.Data
        company_2_api_secret: DF.Password
        active_company: DF.Select

    def update_multi_company_details(
            self,
            company_1_name: str,
            company_1_api_key: str,
            company_1_api_secret: str,
            company_2_name: str,
            company_2_api_key: str,
            company_2_api_secret: str,
    ):
        """Update multi-company API details after validation.

        Args:
            company_1_name (str): Name for company 1
            company_1_api_key (str): API key for company 1
            company_1_api_secret (str): API secret for company 1
            company_2_name (str): Name for company 2
            company_2_api_key (str): API key for company 2
            company_2_api_secret (str): API secret for company 2
        """

        # Validate company 1 credentials
        if not self._validate_company_credentials(company_1_api_key, company_1_api_secret):
            frappe.throw(f"Invalid API credentials for {company_1_name}")

        # Validate company 2 credentials
        if not self._validate_company_credentials(company_2_api_key, company_2_api_secret):
            frappe.throw(f"Invalid API credentials for {company_2_name}")

        # Save company details
        self.company_1_name = company_1_name
        self.company_1_api_key = company_1_api_key
        self.company_1_api_secret = company_1_api_secret
        self.company_2_name = company_2_name
        self.company_2_api_key = company_2_api_key
        self.company_2_api_secret = company_2_api_secret

        # Set active company to 1 if not already set
        if not self.active_company:
            self.active_company = "1"

        # Update main API credentials to active company
        self._sync_active_company_credentials()

        self.save()
        return True

    def switch_active_company(self, target_company: str):
        """Switch the active company and update main API credentials.

        Args:
            target_company (str): Target company number ("1" or "2")
        """

        if not self.multiple_companies:
            frappe.throw("Multiple companies mode is not enabled.")

        if target_company not in ["1", "2"]:
            frappe.throw("Invalid company selection. Must be 1 or 2.")

        # Get current company info for logging
        current_company = self.active_company or "1"
        current_company_name = getattr(self, f"company_{current_company}_name", f"Company {current_company}")
        current_api_key = getattr(self, f"company_{current_company}_api_key", "")

        # Verify target company has credentials
        target_api_key = getattr(self, f"company_{target_company}_api_key")
        target_api_secret = getattr(self, f"company_{target_company}_api_secret")
        target_company_name = getattr(self, f"company_{target_company}_name", f"Company {target_company}")

        if not (target_api_key and target_api_secret):
            frappe.throw(f"No API credentials configured for {target_company_name}")

        # Log the company switch attempt
        log_data: FiscalHarmonyLogData = {
            "request_url": "internal://switch_active_company",
            "payload": json.dumps({
                "action": "switch_company",
                "from_company": current_company,
                "from_company_name": current_company_name,
                "from_api_key": current_api_key[-8:] if current_api_key else "None",  # Last 8 chars for security
                "to_company": target_company,
                "to_company_name": target_company_name,
                "to_api_key": target_api_key[-8:] if target_api_key else "None",  # Last 8 chars for security
                "Api secret":target_api_secret,
                "timestamp": datetime.now().isoformat(),
                "user": frappe.session.user
            }, indent=2),
            "status": "In Progress"
        }

        try:
            # Update active company
            self.active_company = target_company

            # Sync main credentials with active company
            self._sync_active_company_credentials()

            # Clear user profile ID as it may be different for the new company
            old_user_profile_id = self.user_profile_id
            self.user_profile_id = ""

            self.save()

            # Update log with success
            log_data["status"] = "Success"
            log_data["response"] = json.dumps({
                "result": "Company switched successfully",
                "new_active_company": target_company,
                "new_company_name": target_company_name,
                "old_user_profile_id": old_user_profile_id,
                "new_user_profile_id": self.user_profile_id
            }, indent=2)
            log_data["response_status_code"] = 200

            # Log the successful switch
            fh_log(log_data)

            frappe.msgprint(f"Successfully switched from {current_company_name} to {target_company_name}")

            return True

        except Exception as e:
            # Log the failure
            log_data["status"] = "Failure"
            log_data["error_details"] = f"Failed to switch company: {str(e)}"
            log_data["response_status_code"] = 500
            log_data["response"] = json.dumps({
                "error": str(e),
                "attempted_switch": f"{current_company_name} -> {target_company_name}"
            }, indent=2)

            fh_log(log_data)

            # Re-raise the exception
            raise
    def _validate_company_credentials(self, api_key: str, api_secret: str) -> bool:
        """Validate company API credentials against Fiscal Harmony.

        Args:
            api_key (str): The API key to validate
            api_secret (str): The API secret to validate

        Returns:
            bool: True if credentials are valid, False otherwise
        """

        headers = self.__get_headers(api_key)

        try:
            response = requests.get(
                self.__get_request_url("/fiscaldevice"),
                headers=headers,
                timeout=FiscalHarmonySettings.__TIMEOUT,
            )
            return response.ok
        except (TimeoutError, requests.exceptions.RequestException):
            return False

    def _sync_active_company_credentials(self):
        """Sync main API credentials with the active company's credentials."""

        if not self.multiple_companies or not self.active_company:
            return

        active_company = self.active_company
        self.api_key = getattr(self, f"company_{active_company}_api_key")
        self.api_secret = getattr(self, f"company_{active_company}_api_secret")

    def validate(self):
        """Validate the Fiscal Harmony Settings form data."""

        # Original validation
        url_regex = r"^https://[a-z]+\.([a-z]+\.)*(co\.zw|com)/[a-z]+$"

        if not re.match(url_regex, self.endpoint):
            frappe.throw("Please enter a valid URL for the endpoint, then try again.")

        # Multi-company validation
        if self.multiple_companies:
            if not (self.company_1_name and self.company_2_name):
                frappe.throw("Both company names are required when multiple companies is enabled.")

            if not (self.company_1_api_key and self.company_1_api_secret and
                    self.company_2_api_key and self.company_2_api_secret):
                frappe.throw("API credentials for both companies are required when multiple companies is enabled.")

            # Sync main credentials if active company is set
            if self.active_company:
                self._sync_active_company_credentials()

    @frappe.whitelist()
    def get_active_company_info(self):
        """Get information about the currently active company.

        Returns:
            dict: Information about the active company
        """

        if not self.multiple_companies:
            return {"single_company_mode": True}

        active_company = self.active_company or "1"
        company_name = getattr(self, f"company_{active_company}_name", f"Company {active_company}")

        return {
            "multiple_companies": True,
            "active_company": active_company,
            "active_company_name": company_name,
            "company_1_name": self.company_1_name,
            "company_2_name": self.company_2_name,
        }

    def __encode_data(self, data: dict) -> str:
        """Encodes the given data as a valid JSON string for transmitting.

        Args:
            data (dict): The data to be processed.

        Returns:
            str: The JSON representation of the given data."""

        return json.dumps(data, separators=(",", ":"), sort_keys=True)

    def __make_request(self, route: str) -> requests.Response:
        """Generates and processes a standard GET request to the Fiscal Harmony API based on the\
            given route.

        Args:
            route (str): The route to request against.

        Returns:
            requests.Response: The response from the Fiscal Harmony platform."""

        request_url = self.__get_request_url(route)
        headers = self.__get_headers()
        log_data: FiscalHarmonyLogData = {
            "request_url": request_url,
        }

        try:
            response = requests.get(
                request_url,
                headers=headers,
                timeout=FiscalHarmonySettings.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            log_data["response"] = json.dumps(response.json(), indent=2)
            response.raise_for_status()

            log_data["status"] = "Success"
            self.__update_last_successful_request()

        except TimeoutError:
            log_data["status"] = "Failure"
            log_data["error_details"] = ""
            log_data["response_status_code"] = 500
            fh_log(log_data)
            frappe.throw("The connection timed out.")

        except requests.exceptions.HTTPError:
            log_data["error_details"] = response.reason
            if response.status_code == 401:
                log_data["status"] = "Unauthorised"
            else:
                log_data["status"] = "Failure"

        fh_log(log_data)

        return response

    def __get_request_url(self, route: str) -> str:
        """Constructs and returns the route for the API request.

        Args:
            route (str): The path for the request.

        Returns:
            str: The constructed URL."""

        if route.startswith(r"/"):
            return self.endpoint + route

        return f"{self.endpoint}/{route}"

    def __get_headers(self, api_key: str | None = None) -> dict[str, str]:
        """Generate headers using the active company's API key."""

        if self.multiple_companies and self.active_company:
            api_key = getattr(self, f"company_{self.active_company}_api_key")
        else:
            api_key = self.api_key if api_key is None else api_key

        return {
            "X-Api-Key": api_key,
            "X-Application": "ESkill",
            "X-App-Station": "ERPNext",
        }

    def __get_signed_headers(self, payload: str) -> dict[str, str]:
        """Generate signed headers using the active company's credentials."""

        if self.multiple_companies and self.active_company:
            api_key = getattr(self, f"company_{self.active_company}_api_key")
            api_secret = self.get_password(f"company_{self.active_company}_api_secret")

        else:
            api_key = self.api_key
            api_secret = self.get_password("api_secret")

        signature = self.__sign_payload(payload, api_secret)

        return {
            "X-Api-Key": api_key,
            "X-Api-Signature": signature,
            "X-Application": "ESkill",
            "X-App-Station": "ERPNext",
            "Content-Type": "application/json",
        }

    def __process_mappings(self, route_name: str, mapping_dict: dict[str, str]):
        """Processes changes made to the mappaing tables.

        Args:
            route_name (str): The path for the mapping in Fiscal Harmony.\
                Should be "tax" or "currency".
            mapping_dict (dict[str, str]): Dictionary of Fiscal Harmony fields\
                mapped to ERPNext fields."""

        if not self.user_profile_id:
            return

        def get_data(mapping) -> str:
            data = {"UserId": int(self.user_profile_id)}

            for fh_field, erp_field in mapping_dict.items():
                data[fh_field] = mapping.get(erp_field)

            if mapping.get(f"{route_name}_id"):
                data["Id"] = mapping.get(f"{route_name}_id")

            return self.__encode_data(data)

        mappings: set[int] = set()
        posting_url = self.__get_request_url(f"/{route_name}mapping")
        for mapping in self.get(f"{route_name}_mappings"):
            data = get_data(mapping)
            log_data: FiscalHarmonyLogData = {
                "request_url": posting_url,
                "payload": json.dumps(json.loads(data), indent=2),
            }
            headers = self.__get_signed_headers(data)
            try:
                if mapping.get(f"{route_name}_id"):
                    url = self.__get_request_url(
                        f"/{route_name}mapping/{mapping.get(route_name + '_id')}"
                    )
                    log_data["request_url"] = url
                    response = requests.put(
                        url,
                        headers=headers,
                        data=data,
                        timeout=FiscalHarmonySettings.__TIMEOUT,
                    )
                    mappings.add(int(mapping.get(f"{route_name}_id")))

                else:
                    response = requests.post(
                        posting_url,
                        headers=headers,
                        data=data,
                        timeout=FiscalHarmonySettings.__TIMEOUT,
                    )

                    if response.ok:
                        mapping.set(f"{route_name}_id", response.json()["Id"])
                        mappings.add(int(mapping.get(f"{route_name}_id")))

                log_data["response_status_code"] = response.status_code
                log_data["response"] = json.dumps(response.json(), indent=2)
                response.raise_for_status()

                log_data["status"] = "Success"
                self.__update_last_successful_request()

            except TimeoutError:
                log_data["status"] = "Failure"
                log_data["error_details"] = (
                    f"Failed when uploading/updating {route_name} mappings."
                )
                log_data["response_status_code"] = 500

            except requests.exceptions.HTTPError:
                log_data["error_details"] = (
                    f"{response.reason} whilst uploading/updating {route_name} mappings."
                )
                match response.status_code:
                    case 400:
                        log_data["status"] = "Invalid JSON"
                    case 401:
                        log_data["status"] = "Unauthorised"
                        log_data["signature_valid"] = False
                    case _:
                        log_data["status"] = "Failure"

            finally:
                fh_log(log_data)

            if not response.ok:
                frappe.throw(
                    f"Failed to validate {route_name} mappings.<br/>{response.reason}",
                    title=FiscalHarmonySettings.__ERROR_TITLE,
                )

        self.save()

        response = self.__make_request(f"/{route_name}mapping")
        if not response.ok:
            return

        for mapping in response.json():
            if mapping["Id"] in mappings:
                continue

            url = self.__get_request_url(f"/{route_name}mapping/{mapping['Id']}")
            log_data: FiscalHarmonyLogData = {
                "request_url": posting_url,
            }

            try:
                requests.delete(
                    url,
                    headers=self.__get_headers(),
                    timeout=FiscalHarmonySettings.__TIMEOUT,
                )

                log_data["response_status_code"] = response.status_code
                log_data["response"] = json.dumps(response.json(), indent=2)
                response.raise_for_status()

                log_data["status"] = "Success"
                self.__update_last_successful_request()

            except TimeoutError:
                log_data["status"] = "Failure"
                log_data["error_details"] = (
                    f"Timed out whilst deleting {route_name} mappings."
                )
                log_data["response_status_code"] = 500

            except requests.exceptions.HTTPError:
                log_data["error_details"] = (
                    f"{response.reason} whilst deleting {route_name} mappings."
                )
                match response.status_code:
                    case 400:
                        log_data["status"] = "Invalid JSON"
                    case 401:
                        log_data["status"] = "Unauthorised"
                        log_data["signature_valid"] = False
                    case _:
                        log_data["status"] = "Failure"

            finally:
                fh_log(log_data)

        frappe.msgprint(
            f"{route_name.capitalize()} mappings successfully validated.",
            f"Validate {route_name.capitalize()} Mappings",
        )

        self.__update_last_successful_request()

    def __sign_payload(self, payload: str, api_secret: str) -> str:
        """Sign the payload using the provided secret."""
        hasher = hmac.new(
            api_secret.encode("utf-8"),
            msg=payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(hasher.digest()).decode("utf-8")

    def __update_last_successful_request(self):
        """Updates the last_successful_request field."""

        self.last_successful_request = datetime.now()
        self.save(ignore_permissions=True)
