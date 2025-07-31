// Copyright (c) 2024, Eskill Trading (Pvt) Ltd

frappe.ui.form.on("Fiscal Harmony Settings", {
  refresh(frm) {
    // Add Custom Buttons
    frm.add_custom_button(__("Check User Profile"), () => checkUserProfile(frm));
    frm.add_custom_button(__("Get Device Info"), () => getDeviceInfo(frm));
    frm.add_custom_button(__("Update API Token"), () => updateApiToken(frm));
    frm.add_custom_button(__("Get Webhook URL"), () => {
      const webhook = `https://${window.location.hostname}/api/method/capture_signatures`;
      frappe.msgprint(
        `<p>To use the webhook, your ERPNext site must use HTTPS.</p>
         <p>The webhook url to enter in the portal is <strong>${webhook}</strong></p>`,
        "Fiscal Harmony Webhook URL"
      );
    });

    // Only show switch org if multi-company is enabled
    if (frm.doc.multiple_companies) {
      frm.add_custom_button(__("Switch Organisation"), () => switchUserOrg(frm));
    }

    // Trigger once, but avoid infinite refresh
    if (!frm.__initial_triggered) {
      frm.__initial_triggered = true;
      frm.trigger("multiple_companies");
    }
  },

  multiple_companies(frm) {
    // Avoid refreshing everything — just update fields
    if (frm.doc.multiple_companies) {
      if (!frm.doc.company_1_name && (frm.doc.api_key || frm.doc.api_secret)) {
        frm.set_value('company_1_name', 'Company 1');
        frm.set_value('company_1_api_key', frm.doc.api_key);
        frm.set_value('company_1_api_secret', frm.doc.api_secret);
        frm.set_value('active_company', '1');
      }
    } else {
      frm.set_value('company_1_name', '');
      frm.set_value('company_1_api_key', '');
      frm.set_value('company_1_api_secret', '');
      frm.set_value('company_2_name', '');
      frm.set_value('company_2_api_key', '');
      frm.set_value('company_2_api_secret', '');
      frm.set_value('active_company', '');
    }

    // Refresh only the relevant fields
    frm.refresh_fields([
      'company_1_name', 'company_1_api_key', 'company_1_api_secret',
      'company_2_name', 'company_2_api_key', 'company_2_api_secret',
      'active_company'
    ]);
  },

  check_supported_currencies(frm) {
    frappe.call({
      method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.check_supported_currencies",
      args: {
        name: frm.doc.name
      },
      callback: () => frm.reload_doc()
    });
  },

  validate_currency_mappings(frm) {
    if (!(frm.doc.api_key && frm.doc.api_secret) || frm.is_dirty()) return;

    frappe.call({
      method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.validate_currency_mappings",
      args: {
        name: frm.doc.name
      },
      callback: () => frm.reload_doc()
    });
  },

  validate_tax_mappings(frm) {
    if (!(frm.doc.api_key && frm.doc.api_secret) || frm.is_dirty()) return;

    frappe.call({
      method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.validate_tax_mappings",
      args: {
        name: frm.doc.name
      },
      callback: () => frm.reload_doc()
    });
  }
});

/**
 * Handle API token update prompt
 */
const updateApiToken = (frm) => {

  if (frm.doc.multiple_companies) {
    updateMultiCompanyApiTokens(frm);
  } else {
    updateSingleCompanyApiToken(frm);
  }
};

const updateSingleCompanyApiToken = (frm) => {
  frappe.prompt([
    {
      label: "API Key",
      fieldname: "api_key",
      fieldtype: "Data",
      reqd: true,
      default: frm.doc.api_key
    },
    {
      label: "API Secret",
      fieldname: "api_secret",
      fieldtype: "Password",
      reqd: true
    }
  ], (values) => {
    if (!validateApiCredentials(values.api_key, values.api_secret)) return;

    frappe.call({
      method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.validate_api_details",
      args: {
        name: frm.doc.name,
        api_key: values.api_key,
        api_secret: values.api_secret
      },
      callback: () => frm.reload_doc()
    });
  }, "Update API Key & Secret", "Submit");
};

const updateMultiCompanyApiTokens = (frm) => {
  frappe.prompt([
    { fieldtype: "Section Break", label: "Company 1 Details", fieldname: "company_1_section" },
    {
      label: "Company 1 Name", fieldname: "company_1_name", fieldtype: "Data", reqd: true,
      default: frm.doc.company_1_name || "Company 1"
    },
    {
      label: "Company 1 API Key", fieldname: "company_1_api_key", fieldtype: "Data", reqd: true,
      default: frm.doc.company_1_api_key
    },
    {
      label: "Company 1 API Secret", fieldname: "company_1_api_secret", fieldtype: "Password", reqd: true
    },
    { fieldtype: "Section Break", label: "Company 2 Details", fieldname: "company_2_section" },
    {
      label: "Company 2 Name", fieldname: "company_2_name", fieldtype: "Data", reqd: true,
      default: frm.doc.company_2_name || "Company 2"
    },
    {
      label: "Company 2 API Key", fieldname: "company_2_api_key", fieldtype: "Data", reqd: true,
      default: frm.doc.company_2_api_key
    },
    {
      label: "Company 2 API Secret", fieldname: "company_2_api_secret", fieldtype: "Password", reqd: true
    }
  ], (values) => {
    if (!validateApiCredentials(values.company_1_api_key, values.company_1_api_secret)) {
      frappe.throw("Please provide valid API credentials for Company 1.");
    }
    if (!validateApiCredentials(values.company_2_api_key, values.company_2_api_secret)) {
      frappe.throw("Please provide valid API credentials for Company 2.");
    }

    frappe.call({
      method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.update_multi_company_details",
      args: {
        name: frm.doc.name,
        company_1_name: values.company_1_name,
        company_1_api_key: values.company_1_api_key,
        company_1_api_secret: values.company_1_api_secret,
        company_2_name: values.company_2_name,
        company_2_api_key: values.company_2_api_key,
        company_2_api_secret: values.company_2_api_secret
      },
      callback: (r) => {
        if (r.message) {
          frappe.msgprint("Multi-company API details updated successfully.");
          frm.reload_doc();
        }
      }
    });
  }, "Update Multi-Company API Details", "Submit");
};

const switchUserOrg = (frm) => {
  if (!frm.doc.multiple_companies) {
    frappe.msgprint("Multiple companies mode is not enabled.");
    return;
  }

  if (!(frm.doc.company_1_api_key && frm.doc.company_2_api_key)) {
    frappe.msgprint("Please configure API keys for both companies first.");
    return;
  }

  const current = parseInt(frm.doc.active_company || "1");
  const next = current === 1 ? 2 : 1;

  const currentName = current === 1 ? frm.doc.company_1_name : frm.doc.company_2_name;
  const nextName = next === 1 ? frm.doc.company_1_name : frm.doc.company_2_name;

  frappe.confirm(
    `Switch from <strong>${currentName}</strong> to <strong>${nextName}</strong>?<br><br>This will change the active API credentials.`,
    () => {
      frappe.call({
        method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.switch_active_company",
        args: {
          name: frm.doc.name,
          target_company: next
        },
        callback: (r) => {
          if (r.message) {
            frappe.show_alert({ message: `Switched to ${nextName}`, indicator: "green" });
            frm.reload_doc();
          }
        }
      });
    }
  );
};

const validateApiCredentials = (key, secret) => {
  const keyRegex = /^[A-Z\d]{32}$/;
  const secretRegex = /^[a-zA-Z\d\/\+]{86}==$/;

  if (!keyRegex.test(key)) {
    frappe.throw("Please provide a valid API key.");
    return false;
  }

  if (!secretRegex.test(secret)) {
    frappe.throw("Please provide a valid API secret.");
    return false;
  }

  return true;
};

const checkUserProfile = (frm) => {
  if (!(frm.doc.api_key && frm.doc.api_secret) || frm.is_dirty()) return;

  frappe.call({
    method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.check_user_profile",
    args: {
      name: frm.doc.name
    },
    callback: function (r) {
      if (!r.exc) { // no server exception
        frappe.msgprint(__('User profile check successful.'));
        frm.reload_doc();
      }
    }
  });
};


const getDeviceInfo = (frm) => {
  if (!(frm.doc.api_key && frm.doc.api_secret) || frm.is_dirty()) return;

  frappe.call({
    method: "erpnext_fiscalisation.fiscal_harmony_integration.doctype.fiscal_harmony_settings.fiscal_harmony_settings.get_device_info",
    args: {
      name: frm.doc.name
    },
    callback: () => frm.reload_doc()
  });
};