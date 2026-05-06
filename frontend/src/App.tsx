import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AIHealthPage from "./pages/AIHealthPage";
import CapturePage from "./pages/CapturePage";
import DashboardPage from "./pages/DashboardPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReviewPage from "./pages/ReviewPage";
import TrashPage from "./pages/TrashPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<UploadPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:id" element={<ReviewPage />} />
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
