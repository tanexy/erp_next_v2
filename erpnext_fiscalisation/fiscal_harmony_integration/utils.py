# Copyright (c) 2025, Eskill Trading (Pvt) Ltd and contributors
# For license information, please see license.txt

import base64
import hashlib
import hmac
import json
import requests
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import frappe
from erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_log.fiscal_harmony_log import (
    fh_log,
    FiscalHarmonyLogData,
)

if TYPE_CHECKING:
    from frappe.model.document import Document

class FiscalHarmonyBase:
    """Mixin for Fiscal Harmony API interactions."""

    __TIMEOUT = 30
    __ERROR_TITLE = "Fiscal Harmony Error"

    def make_request(self, route: str) -> requests.Response:
        request_url = self.get_request_url(route)
        headers = self.get_headers()
        log_data: FiscalHarmonyLogData = {
            "request_url": request_url,
        }

        try:
            response = requests.get(
                request_url,
                headers=headers,
                timeout=self.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            try:
                log_data["response"] = json.dumps(response.json(), indent=2)
            except Exception:
                log_data["response"] = response.text
            response.raise_for_status()

            log_data["status"] = "Success"
            self.update_last_successful_request()

        except (TimeoutError, requests.exceptions.Timeout):
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

    def get_request_url(self, route: str) -> str:
        endpoint = self.endpoint
        if route.startswith(r"/"):
            return endpoint + route
        return f"{endpoint}/{route}"

    def get_headers(self, api_key: Optional[str] = None) -> dict[str, str]:
        if api_key is None:
            api_key = self.get_api_key()
        return {
            "X-Api-Key": api_key,
            "X-Application": "ESkill",
            "X-App-Station": "ERPNext",
        }

    def get_signed_headers(self, payload: str) -> dict[str, str]:
        api_key = self.get_api_key()
        api_secret = self.get_api_secret()
        signature = self.sign_payload(payload, api_secret)

        return {
            "X-Api-Key": api_key,
            "X-Api-Signature": signature,
            "X-Application": "ESkill",
            "X-App-Station": "ERPNext",
            "Content-Type": "application/json",
        }

    def get_api_key(self) -> str:
        if hasattr(self, "get_active_api_key"):
            return self.get_active_api_key()
        return self.api_key

    def get_api_secret(self) -> str:
        if hasattr(self, "get_active_api_secret"):
            return self.get_active_api_secret()

        if getattr(self, "doctype", None) == "Fiscal Harmony Warehouse API Credential":
            return frappe.utils.password.get_decrypted_password(self.doctype, self.name, "api_secret")

        return self.get_password("api_secret")

    def sign_payload(self, payload: str, api_secret: str) -> str:
        hasher = hmac.new(
            api_secret.encode("utf-8"),
            msg=payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(hasher.digest()).decode("utf-8")

    def update_last_successful_request(self):
        self.last_successful_request = datetime.now()
        if getattr(self, "doctype", None) == "Fiscal Harmony Settings":
            self.save(ignore_permissions=True)
        elif hasattr(self, "parent_doc"):
            self.parent_doc.save(ignore_permissions=True)

    def encode_data(self, data: dict) -> str:
        return json.dumps(data, separators=(",", ":"), sort_keys=True)

    def get_device_info(self, title: str = "Fiscal Device Info"):
        """Displays the Fiscal Harmony fiscal device config to the user."""

        response = self.make_request("/fiscaldevice")
        if not response.ok:
            frappe.throw("Failed to fetch the device status.")

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

        frappe.msgprint(message, title)

    def download_fiscal_pdf(self, signature: "Document") -> bytes | None:
        """Download the fiscal PDF listed on the signature and attach to the invoice.

        Args:
            signature (Document): The document that stores the fiscal result.

        Returns:
            bytes|None: Returns the content of the downloaded PDF."""

        if not signature.fiscal_harmony_filename:
            frappe.log_error(
                "Fiscal Harmony: PDF Error",
                f"No PDF available for signature {signature.name}.",
            )
            return None

        request_url = self.get_request_url(
            f"/download/{signature.fiscal_harmony_filename}"
        )
        headers = self.get_headers()
        log_data: FiscalHarmonyLogData = {
            "request_url": request_url,
        }

        try:
            response = requests.get(
                request_url,
                headers=headers,
                timeout=self.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            log_data["response"] = str(response.content)
            response.raise_for_status()

            log_data["status"] = "Success"
            self.update_last_successful_request()

        except (TimeoutError, requests.exceptions.Timeout):
            log_data["status"] = "Failure"
            log_data["error_details"] = "The connection timed out."
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
            frappe.throw(f"HTTP Error: {response.reason}")

        except Exception as e:
            log_data["status"] = "Failure"
            log_data["error_details"] = str(e)
            fh_log(log_data)
            frappe.throw(f"Failed to download PDF: {str(e)}")

        fh_log(log_data)
        return response.content

    def fetch_signature_data(self, signature: "Document"):
        """Fetches the data of an already fiscalised signature that did not have its data returned
            via webhook.

        Args:
            signature (Document): The document that stores the fiscal result."""

        if not signature.fiscal_harmony_id or signature.fdms_url:
            return

        url = self.get_request_url("status")
        data = [str(signature.fiscal_harmony_id)]
        log_data: FiscalHarmonyLogData = {
            "request_url": url,
            "payload": json.dumps(data, indent=2),
        }
        payload = self.encode_data(data)
        headers = self.get_signed_headers(payload)

        try:
            response = requests.post(
                url,
                data=payload,
                headers=headers,
                timeout=self.__TIMEOUT,
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
            self.update_last_successful_request()

        except (TimeoutError, requests.exceptions.Timeout):
            signature.is_retry = True
            log_data["status"] = "Failure"
            log_data["error_details"] = "Timed out whilst signing transaction."
            log_data["response_status_code"] = 500
            fh_log(log_data)


        except Exception as e:
            signature.is_retry = True
            log_data["status"] = "Failure"
            log_data["error_details"] = str(e)
            fh_log(log_data)

        finally:
            signature.save(ignore_permissions=True)
            if signature.fiscal_harmony_filename:
                signature.download_or_generate_pdf()

    def fiscalise_transaction(self, signature: "Document"):
        """Fiscalises the invoice/credit note attached to the given signature.

        Args:
            signature (Document): The document that stores the fiscal result."""

        data = signature.get_payload_data()
        payload = self.encode_data(data)
        headers = self.get_signed_headers(payload)
        url = self.get_request_url(
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
                timeout=self.__TIMEOUT,
            )
            log_data["response_status_code"] = response.status_code
            try:
                log_data["response"] = json.dumps(response.json(), indent=2)
            except json.JSONDecodeError:
                log_data["response"] = response.text

            response.raise_for_status()

            signature.fiscal_harmony_id = response.text
            log_data["status"] = "Success"
            self.update_last_successful_request()

        except Exception as e:
            signature.is_retry = True
            log_data["status"] = "Failure"
            log_data["error_details"] = str(e)
            fh_log(log_data)

        finally:
            signature.save(ignore_permissions=True)

    def process_mappings(self, route_name: str, mapping_dict: dict[str, str]):
        if not self.user_profile_id:
            return

        def get_data(mapping) -> str:
            data = {"UserId": int(self.user_profile_id)}
            for fh_field, erp_field in mapping_dict.items():
                data[fh_field] = mapping.get(erp_field)
            if mapping.get(f"{route_name}_id"):
                data["Id"] = mapping.get(f"{route_name}_id")
            return self.encode_data(data)

        mappings: set[int] = set()
        posting_url = self.get_request_url(f"/{route_name}mapping")

        # Get correct source of mappings (always from global settings)
        is_global = getattr(self, "doctype", None) == "Fiscal Harmony Settings"
        parent_doc = self if is_global else self.parent_doc
        all_mappings = parent_doc.get(f"{route_name}_mappings")

        # Filter mappings for this context (either specific warehouse or global)
        context_warehouse = getattr(self, "warehouse", None)
        relevant_mappings = [m for m in all_mappings if m.warehouse == context_warehouse]

        for mapping in relevant_mappings:
            data = get_data(mapping)
            log_data: FiscalHarmonyLogData = {
                "request_url": posting_url,
                "payload": json.dumps(json.loads(data), indent=2),
            }
            headers = self.get_signed_headers(data)
            try:
                if mapping.get(f"{route_name}_id"):
                    url = self.get_request_url(
                        f"/{route_name}mapping/{mapping.get(route_name + '_id')}"
                    )
                    log_data["request_url"] = url
                    response = requests.put(
                        url,
                        headers=headers,
                        data=data,
                        timeout=self.__TIMEOUT,
                    )
                    mappings.add(int(mapping.get(f"{route_name}_id")))
                else:
                    response = requests.post(
                        posting_url,
                        headers=headers,
                        data=data,
                        timeout=self.__TIMEOUT,
                    )
                    if response.ok:
                        mapping.set(f"{route_name}_id", response.json()["Id"])
                        mappings.add(int(mapping.get(f"{route_name}_id")))

                log_data["response_status_code"] = response.status_code
                log_data["response"] = json.dumps(response.json(), indent=2)
                response.raise_for_status()
                log_data["status"] = "Success"
                self.update_last_successful_request()

            except Exception as e:
                log_data["status"] = "Failure"
                log_data["error_details"] = str(e)
                fh_log(log_data)
                frappe.throw(f"Failed to validate {route_name} mappings.<br/>{str(e)}")

            finally:
                fh_log(log_data)

        self.save()

        response = self.make_request(f"/{route_name}mapping")
        if not response.ok:
            return

        for mapping in response.json():
            if mapping["Id"] in mappings:
                continue

            url = self.get_request_url(f"/{route_name}mapping/{mapping['Id']}")
            log_data: FiscalHarmonyLogData = {
                "request_url": url,
            }

            try:
                requests.delete(
                    url,
                    headers=self.get_headers(),
                    timeout=self.__TIMEOUT,
                )
                log_data["status"] = "Success"
                self.update_last_successful_request()

            except Exception as e:
                log_data["status"] = "Failure"
                log_data["error_details"] = str(e)
            finally:
                fh_log(log_data)

        # frappe.msgprint(
        #     f"{route_name.capitalize()} mappings successfully validated.",
        #     f"Validate {route_name.capitalize()} Mappings",
        # )
