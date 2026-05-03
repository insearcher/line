(function attachDashboardAuth(root) {
  function tokenFromHash(hash) {
    const value = String(hash || "").replace(/^#/, "");
    const params = new URLSearchParams(value);
    return params.get("dashboardToken") || "";
  }

  function authHeaders(token) {
    if (!token) {
      return {};
    }
    return { Authorization: `Bearer ${token}` };
  }

  root.LineDashboardAuth = {
    authHeaders,
    tokenFromHash,
  };
})(globalThis);
