import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CapturePage from "./pages/CapturePage";
import DashboardPage from "./pages/DashboardPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReviewPage from "./pages/ReviewPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<UploadPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:id" element={<ReviewPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
        </Route>
        {/* Capture page has its own full-screen layout (no sidebar) */}
        <Route path="/capture" element={<CapturePage />} />
      </Routes>
    </BrowserRouter>
  );
}
