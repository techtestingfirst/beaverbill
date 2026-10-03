import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

export default defineConfig({
  // `frontendRoute` is where the site serves the app. The plugin proxies the
  // bench while you develop, and builds into the app's public and www folders.
  plugins: [frappeui({ frontendRoute: '/beaverbill' }), vue()],
  server: {
    proxy: {
      // Provider-hosted pages live on the bench, not in the SPA. Without
      // these, dev history-fallback serves index.html and the router rewrites
      // them to /beaverbill/<page> (NotFound).
      '/razorpay_checkout': 'http://beaverbill.localhost:8000',
      '/stripe_checkout': 'http://beaverbill.localhost:8000',
      '/payment-success': 'http://beaverbill.localhost:8000',
      '/payment-failed': 'http://beaverbill.localhost:8000',
      '/website_script.js': 'http://beaverbill.localhost:8000',
      '/website.css': 'http://beaverbill.localhost:8000',
      // frappe.call POSTs to "/" with X-Frappe-CMD (see razorpay_checkout.js
      // make_payment). Vite answers 404, confirmation never reaches bench,
      // invoice stays unpaid. InvoiceDetail now navigates to backend absolute
      // URL, this proxy is safety net for relative visits via :8080.
      '^/$': 'http://beaverbill.localhost:8000',
    },
  },
})
