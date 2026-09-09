import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import DocumentsPage from "./pages/DocumentsPage";
import FlowPage from "./pages/FlowPage";
import "./pages/flow.css";
import InboxPage from "./pages/InboxPage";
import LandingPage from "./pages/LandingPage";
import "./pages/landing.css";
import StoreDetailPage from "./pages/StoreDetailPage";
import StoresPage from "./pages/StoresPage";
import TrashPage from "./pages/TrashPage";
import VisitDetailPage from "./pages/VisitDetailPage";
import VisitReviewPage from "./pages/VisitReviewPage";
import VisitsPage from "./pages/VisitsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Standalone full-screen surfaces — no sidebar, no chrome. */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/flow" element={<FlowPage />} />
        <Route element={<Layout />}>
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/stores" element={<StoresPage />} />
          <Route path="/stores/:id" element={<StoreDetailPage />} />
          <Route path="/visits" element={<VisitsPage />} />
          <Route path="/visits/:id" element={<VisitDetailPage />} />
          <Route path="/visits/:visitId/review/:docId" element={<VisitReviewPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/trash" element={<TrashPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
