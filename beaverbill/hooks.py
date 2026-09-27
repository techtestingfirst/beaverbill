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
