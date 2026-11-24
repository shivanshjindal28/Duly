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
import { wakeBackend } from "./lib/wake";
import "./theme/global.css";
import "./theme/common.css";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AppShell } from "./layout/AppShell";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { AssistantPage } from "./pages/AssistantPage";
import { BankChangesPage } from "./pages/BankChangesPage";
import { AuditPage } from "./pages/AuditPage";
import { ComparePage } from "./pages/ComparePage";
import { ControlsReportPage } from "./pages/ControlsReportPage";
import { DashboardPage } from "./pages/DashboardPage";
import { QueuePage } from "./pages/QueuePage";
import { SupplierPortalPage } from "./pages/SupplierPortalPage";
import { SupplierRiskPage } from "./pages/SupplierRiskPage";
import { DemoControlsPage } from "./pages/DemoControlsPage";
import { ImpactPage } from "./pages/ImpactPage";
import { InboxPage } from "./pages/InboxPage";
import { ArchitecturePage } from "./pages/ArchitecturePage";
import { AssumptionsPage } from "./pages/AssumptionsPage";
import { PolicyPage } from "./pages/PolicyPage";
import { TrustPage } from "./pages/TrustPage";
import { LoginPage } from "./pages/LoginPage";
import { InvoiceDetailPage } from "./pages/InvoiceDetailPage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PaymentsPage } from "./pages/PaymentsPage";
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
              { path: "/invoices/:id/compare", element: <ComparePage /> },
              { path: "/upload", element: <UploadPage /> },
              { path: "/inbox", element: <InboxPage /> },
              { path: "/receiving", element: <ReceivingPage /> },
              { path: "/approvals", element: <ApprovalsPage /> },
              { path: "/admin/demo", element: <DemoControlsPage /> },
              { path: "/policy", element: <PolicyPage /> },
              { path: "/audit", element: <AuditPage /> },
              { path: "/controls", element: <ControlsReportPage /> },
              { path: "/bank-changes", element: <BankChangesPage /> },
              { path: "/suppliers", element: <SupplierRiskPage /> },
              { path: "/payments", element: <PaymentsPage /> },
              { path: "/dashboard", element: <DashboardPage /> },
              { path: "/queue", element: <QueuePage /> },
              { path: "/portal", element: <SupplierPortalPage /> },
              { path: "/assistant", element: <AssistantPage /> },
              { path: "/impact", element: <ImpactPage /> },
              { path: "/architecture", element: <ArchitecturePage /> },
              { path: "/trust", element: <TrustPage /> },
              { path: "/assumptions", element: <AssumptionsPage /> },
            ],
          },
        ],
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

wakeBackend(); // hosted demo: start waking the sleeping API right away
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
