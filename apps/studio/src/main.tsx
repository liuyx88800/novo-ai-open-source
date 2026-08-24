import React from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConfigProvider, App as AntdApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "./globals.css";

import { initSession } from "./studio/session-init";
import { installApiBridge } from "./studio/api-bridge";
import CreatePage from "./studio/create/page";
import DramaPage from "./studio/drama/page";
import DramaDetailPage from "./studio/drama/[id]/page";
import WorksPage from "./studio/works/page";
import SharePage from "./studio/share/[slug]/page";

installApiBridge();
initSession();

function installHostBridge() {
  const hostRouteForPage = (page: string) => (page === "vz-drama" ? "/drama" : page === "vz-agent" ? "/agent" : "");
  const navigateToRoute = (route: string) => {
    if (!route) return;
    const current = window.location.hash || "";
    if (current !== `#${route}`) window.location.replace(`#${route}`);
  };
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (data && typeof data === "object" && data.type === "studio-page-active") navigateToRoute(hostRouteForPage(String(data.page || "")));
  });
  try {
    const hash = window.location.hash || "";
    if (hash === "" || hash === "#" || hash === "#/") navigateToRoute(hostRouteForPage(localStorage.getItem("studio_active_page") || ""));
  } catch {
    // ignore
  }
}
installHostBridge();

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

class AppErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean; message: string }> {
  state = { hasError: false, message: "" };
  static getDerivedStateFromError(error: unknown) {
    return { hasError: true, message: error instanceof Error ? error.message : "页面渲染异常" };
  }
  componentDidCatch(error: unknown, info: React.ErrorInfo) {
    console.error("[AppErrorBoundary]", error, info.componentStack || "");
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, fontFamily: "system-ui, sans-serif", color: "#334155" }}>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <p style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>页面加载出现异常</p>
            <p style={{ fontSize: 13, color: "#94a3b8", margin: "0 0 16px", wordBreak: "break-all" }}>{this.state.message}</p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{ padding: "8px 18px", borderRadius: 8, border: "1px solid #cbd5e1", background: "#fff", cursor: "pointer", fontSize: 14 }}
            >
              重新加载
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function Root() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/agent" element={<CreatePage />} />
        <Route path="/create" element={<CreatePage />} />
        <Route path="/drama" element={<DramaPage />} />
        <Route path="/drama/:id" element={<DramaDetailPage />} />
        <Route path="/works" element={<WorksPage />} />
        <Route path="/share/:slug" element={<SharePage />} />
        <Route path="/" element={<Navigate to="/agent" replace />} />
        <Route path="*" element={<Navigate to="/agent" replace />} />
      </Routes>
    </HashRouter>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <AntdApp>
          <AppErrorBoundary>
            <Root />
          </AppErrorBoundary>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);