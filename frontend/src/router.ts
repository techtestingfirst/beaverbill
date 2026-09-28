import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { isLoggedIn, refreshSession, session } from './auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('./pages/Login.vue'), meta: { public: true, title: 'Log in' } },
  { path: '/signup', component: () => import('./pages/Signup.vue'), meta: { public: true, title: 'Sign up' } },
  { path: '/verify', component: () => import('./pages/VerifyEmail.vue'), meta: { public: true, title: 'Verify email' } },
  { path: '/forgot-password', component: () => import('./pages/ForgotPassword.vue'), meta: { public: true, title: 'Reset password' } },
  { path: '/', component: () => import('./pages/Dashboard.vue'), meta: { title: 'Dashboard' } },
  { path: '/services', component: () => import('./pages/Services.vue'), meta: { title: 'Services' } },
  { path: '/services/:name', component: () => import('./pages/ServiceDetail.vue'), meta: { title: 'Service detail' } },
  { path: '/catalog', component: () => import('./pages/Catalog.vue'), meta: { title: 'Catalog' } },
  { path: '/catalog/:name', component: () => import('./pages/ProductDetail.vue'), meta: { title: 'Product' } },
  { path: '/cart', component: () => import('./pages/Cart.vue'), meta: { title: 'Cart' } },
  { path: '/checkout', component: () => import('./pages/Checkout.vue'), meta: { title: 'Checkout' } },
  { path: '/invoices', component: () => import('./pages/Invoices.vue'), meta: { title: 'Payment center' } },
  { path: '/invoices/:name', component: () => import('./pages/InvoiceDetail.vue'), meta: { title: 'Invoice' } },
  { path: '/payment-methods', component: () => import('./pages/PaymentMethods.vue'), meta: { title: 'Payment methods' } },
  { path: '/domains', component: () => import('./pages/Domains.vue'), meta: { title: 'Domains and SSL' } },
  { path: '/backups', component: () => import('./pages/Backups.vue'), meta: { title: 'Backups' } },
  { path: '/addons', component: () => import('./pages/Addons.vue'), meta: { title: 'Add-ons' } },
  { path: '/tickets', component: () => import('./pages/Tickets.vue'), meta: { title: 'Support tickets' } },
  { path: '/tickets/:name', component: () => import('./pages/TicketDetail.vue'), meta: { title: 'Ticket' } },
  { path: '/profile', component: () => import('./pages/Profile.vue'), meta: { title: 'Profile' } },
  { path: '/:path(.*)*', component: () => import('./pages/NotFound.vue'), meta: { public: true, title: 'Not found' } },
]

export const router = createRouter({
  // The same path as `frontendRoute` in vite.config.ts
  history: createWebHistory('/beaverbill'),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  if (!session.loaded) await refreshSession()
  const title = (to.meta.title as string) || 'BeaverBill'
  document.title = `${title} · BeaverBill`
  // Move focus to the main region on navigation for screen readers.
  requestAnimationFrame(() => document.getElementById('main')?.focus({ preventScroll: true }))
  if (to.meta.public) {
    if (isLoggedIn() && ['/login', '/signup'].includes(to.path)) return '/'
    return true
  }
  if (!isLoggedIn()) return { path: '/login', query: { redirect: to.fullPath } }
  return true
})
