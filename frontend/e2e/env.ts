/* Bootstrap password for the throw-away e2e database copies only (data/e2e*.db, git-ignored). Never a real account.
   Override with PYROSCOPE_E2E_ADMIN_PASSWORD in CI. */
export const E2E_ADMIN_PASSWORD = process.env.PYROSCOPE_E2E_ADMIN_PASSWORD || 'E2e-Admin-Passw0rd'
