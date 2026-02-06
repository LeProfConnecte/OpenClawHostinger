import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation, Navigate } from "react-router-dom";
import LoginPage from "@/pages/LoginPage";
import SetupPage from "@/pages/SetupPage";
import AuthCallback from "@/pages/AuthCallback";
import { Toaster } from "@/components/ui/sonner";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Application error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#0f0f10] flex items-center justify-center">
          <div className="text-center max-w-md px-6">
            <h2 className="text-xl font-semibold text-zinc-100 mb-2">Something went wrong</h2>
            <p className="text-zinc-400 text-sm mb-4">
              An unexpected error occurred. Please try refreshing the page.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="bg-[#FF4500] hover:bg-[#E63E00] text-white px-4 py-2 rounded-md text-sm"
            >
              Refresh Page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function AppRouter() {
  const location = useLocation();

  // Check URL fragment (not query params) for session_id - MUST be synchronous
  // This runs BEFORE ProtectedRoute to prevent race conditions
  if (location.hash?.includes('session_id=')) {
    return <AuthCallback />;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<SetupPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <div className="App dark">
      <ErrorBoundary>
        <Toaster data-testid="global-toaster" richColors position="top-center" />
        <BrowserRouter>
          <AppRouter />
        </BrowserRouter>
      </ErrorBoundary>
    </div>
  );
}

export default App;
