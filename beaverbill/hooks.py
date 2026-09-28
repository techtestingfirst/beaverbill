app_name = "beaverbill"
app_title = "BeaverBill"
app_publisher = "Praveen Kumar"
app_description = "Hosting billing software"
app_email = "techtestingfirst@gmail.com"
app_license = "mit"

required_apps = ["frappe"]

# Installation
# ------------
after_install = "beaverbill.setup.after_install"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/beaverbill/css/beaverbill.css"
# app_include_js = "/assets/beaverbill/js/beaverbill.js"

# Load the frontend on every path under /beaverbill
website_route_rules = [
	{"from_route": "/beaverbill/<path:app_path>", "to_route": "beaverbill"},
]


# Send non-GET requests for this app's endpoints as native `application/json`
# bodies instead of form-encoded, per-key JSON-stringified values.
use_json_request_body = True

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
	
# ]

# Single Page Application / Customer Portal Routing Rules
# website_route_rules = [
# ]
# Redirect website users away from /app to /portal
# website_context = {
#     "splash_button_link": "/portal"
# }

# Add standard boot session hook if needed
# has_website_permission = "dhole_bill.api.portal.has_website_permission"


# Phase 1 Desk Guard Interceptor (MUST be a list)
# before_request = [
    
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `dhole_bill/dock/dhole_bill/dhole_bill.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/dhole_bill/css/dhole_bill.css"
# app_include_js = "/assets/dhole_bill/js/dhole_bill.js"

# include js, css files in header of web template
# web_include_css = "/assets/dhole_bill/css/dhole_bill.css"
# web_include_js = "/assets/dhole_bill/js/dhole_bill.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "dhole_bill/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "dhole_bill/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Setup Wizard
# ------------

# open a fresh site's setup in this app's own UI instead of the desk wizard.
# must be a non-desk route (not under /desk or /app); to customize setup within
# desk, use setup_wizard_stages / setup_wizard_complete instead.
# setup_wizard_url = "/dhole_bill/setup"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "dhole_bill.utils.jinja_methods",
# 	"filters": "dhole_bill.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "dhole_bill.install.before_install"
# after_install = "dhole_bill.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "dhole_bill.uninstall.before_uninstall"
# after_uninstall = "dhole_bill.uninstall.after_uninstall"

# Disable / Enable
# ----------------
# Called when this app is logically disabled or re-enabled on a site,
# without uninstalling it. Use this to hide/restore fields this app adds
# to other apps' doctypes.

# before_disable = "dhole_bill.uninstall.before_disable"
# after_disable = "dhole_bill.uninstall.after_disable"
# before_enable = "dhole_bill.install.before_enable"
# after_enable = "dhole_bill.install.after_enable"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "dhole_bill.utils.before_app_install"
# after_app_install = "dhole_bill.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "dhole_bill.utils.before_app_uninstall"
# after_app_uninstall = "dhole_bill.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "dhole_bill.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "dhole_bill.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "dhole_bill.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["dhole_bill.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Hosting Service": "beaverbill.beaverbill.permissions.hosting_service_query_conditions",
	"Hosting Customer": "beaverbill.beaverbill.permissions.hosting_customer_query_conditions",
	"Hosting Order": "beaverbill.beaverbill.permissions.hosting_order_query_conditions",
	"Hosting Invoice": "beaverbill.beaverbill.permissions.hosting_invoice_query_conditions",
	"Hosting Subscription": "beaverbill.beaverbill.permissions.hosting_subscription_query_conditions",
	"Hosting Payment Transaction": "beaverbill.beaverbill.permissions.hosting_payment_query_conditions",
	"Hosting Payment Method": "beaverbill.beaverbill.permissions.hosting_payment_method_query_conditions",
	"Hosting Customer Contact": "beaverbill.beaverbill.permissions.hosting_contact_query_conditions",
	"Hosting Domain": "beaverbill.beaverbill.permissions.hosting_domain_query_conditions",
	"Hosting DNS Record": "beaverbill.beaverbill.permissions.hosting_dns_query_conditions",
	"SSL Certificate": "beaverbill.beaverbill.permissions.ssl_certificate_query_conditions",
	"Service Backup": "beaverbill.beaverbill.permissions.service_backup_query_conditions",
	"Restore Request": "beaverbill.beaverbill.permissions.restore_request_query_conditions",
	"Service Addon": "beaverbill.beaverbill.permissions.service_addon_query_conditions",
	"Service Action": "beaverbill.beaverbill.permissions.service_action_query_conditions",
	"Service Storage Usage": "beaverbill.beaverbill.permissions.service_usage_query_conditions",
	"Customer Notification": "beaverbill.beaverbill.permissions.customer_notification_query_conditions",
	"Security Audit Log": "beaverbill.beaverbill.permissions.security_audit_log_query_conditions",
	"Scoped API Token": "beaverbill.beaverbill.permissions.scoped_api_token_query_conditions",
}

has_permission = {
	"Hosting Service": "beaverbill.beaverbill.permissions.check_service_ownership",
	"Hosting Customer": "beaverbill.beaverbill.permissions.check_customer_ownership",
	"Hosting Order": "beaverbill.beaverbill.permissions.check_order_ownership",
	"Hosting Customer Contact": "beaverbill.beaverbill.permissions.check_contact_ownership",
	"Hosting Domain": "beaverbill.beaverbill.permissions.check_domain_ownership",
	"Hosting DNS Record": "beaverbill.beaverbill.permissions.check_dns_ownership",
	"SSL Certificate": "beaverbill.beaverbill.permissions.check_portal_read_ownership",
	"Service Backup": "beaverbill.beaverbill.permissions.check_portal_read_ownership",
	"Restore Request": "beaverbill.beaverbill.permissions.check_portal_read_ownership",
	"Service Addon": "beaverbill.beaverbill.permissions.check_addon_ownership",
	"Service Action": "beaverbill.beaverbill.permissions.check_action_ownership",
	"Service Storage Usage": "beaverbill.beaverbill.permissions.check_portal_read_ownership",
	"Hosting Invoice": "beaverbill.beaverbill.permissions.check_invoice_ownership",
	"Hosting Payment Transaction": "beaverbill.beaverbill.permissions.check_payment_ownership",
	"Hosting Payment Method": "beaverbill.beaverbill.permissions.check_payment_method_ownership",
	"Hosting Subscription": "beaverbill.beaverbill.permissions.check_portal_read_ownership",
	"Customer Notification": "beaverbill.beaverbill.permissions.check_notification_ownership",
	"Security Audit Log": "beaverbill.beaverbill.permissions.check_staff_only",
	"Scoped API Token": "beaverbill.beaverbill.permissions.check_staff_only",
}

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }
# doc_events = {
	
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "beaverbill.beaverbill.doctype.hosting_subscription.hosting_subscription.process_subscription_renewals",
        "beaverbill.beaverbill.doctype.hosting_service_modification_request.hosting_service_modification_request.apply_due_modifications",
        "beaverbill.beaverbill.doctype.provisioning_operation.provisioning_operation.process_queued_provisioning_operations",
        "beaverbill.beaverbill.doctype.hosting_domain.hosting_domain.process_domain_renewals",
        "beaverbill.beaverbill.doctype.ssl_certificate.ssl_certificate.monitor_certificates",
        "beaverbill.beaverbill.doctype.service_addon.service_addon.process_addon_renewals",
        "beaverbill.beaverbill.backups.run_due_backups",
        "beaverbill.beaverbill.backups.enforce_retention",
        "beaverbill.beaverbill.backups.process_storage_overage",
        "beaverbill.beaverbill.helpdesk_sync.process_helpdesk_sync",
    ],
}

# Testing
# -------

# before_tests = "dhole_bill.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "dhole_bill.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "dhole_bill.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "dhole_bill.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["dhole_bill.utils.before_request"]
# after_request = ["dhole_bill.utils.after_request"]

# Job Events
# ----------
# before_job = ["dhole_bill.utils.before_job"]
# after_job = ["dhole_bill.utils.after_job"]

# after_file_upload = ["dhole_bill.utils.after_file_upload"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"dhole_bill.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []