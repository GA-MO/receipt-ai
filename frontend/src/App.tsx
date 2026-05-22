import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import DocumentsPage from "./pages/DocumentsPage";
import InboxPage from "./pages/InboxPage";
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
        <Route element={<Layout />}>
          <Route path="/" element={<InboxPage />} />
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
