import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-sans-devanagari/400.css";
import "@fontsource/ibm-plex-sans-devanagari/600.css";
import "./i18n";
import { applyTokens } from "./theme/tokens";
import "./theme/global.css";
import "./theme/common.css";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AppShell } from "./layout/AppShell";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { AuditPage } from "./pages/AuditPage";
import { DashboardPage } from "./pages/DashboardPage";
import { QueuePage } from "./pages/QueuePage";
import { SupplierPortalPage } from "./pages/SupplierPortalPage";
import { DemoControlsPage } from "./pages/DemoControlsPage";
import { LoginPage } from "./pages/LoginPage";
import { InvoiceDetailPage } from "./pages/InvoiceDetailPage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReceivingPage } from "./pages/ReceivingPage";
import { UploadPage } from "./pages/UploadPage";

applyTokens();

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function RequireAuth() {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="muted" style={{ padding: 32 }}>Loading...</div>;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function Root() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}

const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        element: <RequireAuth />,
        children: [
          {
            element: <AppShell />,
            children: [
              { path: "/", element: <OverviewPage /> },
              { path: "/invoices", element: <InvoicesPage /> },
              { path: "/invoices/:id", element: <InvoiceDetailPage /> },
              { path: "/upload", element: <UploadPage /> },
              { path: "/receiving", element: <ReceivingPage /> },
              { path: "/approvals", element: <ApprovalsPage /> },
              { path: "/admin/demo", element: <DemoControlsPage /> },
              { path: "/audit", element: <AuditPage /> },
              { path: "/dashboard", element: <DashboardPage /> },
              { path: "/queue", element: <QueuePage /> },
              { path: "/portal", element: <SupplierPortalPage /> },
            ],
          },
        ],
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
