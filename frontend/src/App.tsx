import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AIHealthPage from "./pages/AIHealthPage";
import CapturePage from "./pages/CapturePage";
import DashboardPage from "./pages/DashboardPage";
import DocumentsPage from "./pages/DocumentsPage";
import StoresPage from "./pages/StoresPage";
import TrashPage from "./pages/TrashPage";
import UploadPage from "./pages/UploadPage";
import VisitDetailPage from "./pages/VisitDetailPage";
import VisitReviewPage from "./pages/VisitReviewPage";
import VisitsPage from "./pages/VisitsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<VisitsPage />} />
          <Route path="/visits" element={<VisitsPage />} />
          <Route path="/visits/:id" element={<VisitDetailPage />} />
          <Route path="/visits/:visitId/review/:docId" element={<VisitReviewPage />} />
          <Route path="/stores" element={<StoresPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/trash" element={<TrashPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/ai-health" element={<AIHealthPage />} />
        </Route>
        {/* Capture page has its own full-screen layout (no sidebar) */}
        <Route path="/capture" element={<CapturePage />} />
      </Routes>
    </BrowserRouter>
  );
}
