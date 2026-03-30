// Copyright (c) 2025, Eskill Trading (Pvt) Ltd

frappe.ui.form.on("Fiscal Harmony Warehouse Settings", {
  refresh(frm) {
    // Add Custom Buttons
    frm.add_custom_button(__("Check User Profile"), () => checkUserProfile(frm));
    frm.add_custom_button(__("Get Device Info"), () => getDeviceInfo(frm));
    frm.add_custom_button(__("Update API Token"), () => updateApiToken(frm));
  },

  check_supported_currencies(frm) {
    frappe.call({
      doc: frm.doc,
      method: "check_supported_currencies",
      callback: () => frm.reload_doc()
    });
  },

  validate_currency_mappings(frm) {
    if (!(frm.doc.api_key && frm.doc.api_secret) || frm.is_dirty()) return;

    frappe.call({
      doc: frm.doc,
      method: "validate_currency_mappings",
      callback: () => frm.reload_doc()
    });
  },

  validate_tax_mappings(frm) {
    if (!(frm.doc.api_key && frm.doc.api_secret) || frm.is_dirty()) return;

    frappe.call({
      doc: frm.doc,
      method: "validate_tax_mappings",
      callback: () => frm.reload_doc()
    });
  }
});

/**
 * Handle API token update prompt
 */
const updateApiToken = (frm) => {
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
      doc: frm.doc,
      method: "validate_api_details",
      args: {
        api_key: values.api_key,
        api_secret: values.api_secret
      },
      callback: () => frm.reload_doc()
    });
  }, "Update API Key & Secret", "Submit");
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
    doc: frm.doc,
    method: "check_user_profile",
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
    doc: frm.doc,
    method: "get_device_info",
    callback: () => frm.reload_doc()
  });
};
