import { useParams } from "react-router-dom";
import DocumentReport from "../DocumentReport";

/** Полная страница документа: /documents/:id (второй режим — панель в списке). */
export default function ReportPage() {
  const { documentId } = useParams();
  const id = Number(documentId);

  if (!/^\d+$/.test(documentId ?? "") || !Number.isFinite(id)) {
    return (
      <section className="page">
        <div className="alert error">Некорректный адрес документа</div>
      </section>
    );
  }

  return (
    <section className="page">
      <DocumentReport documentId={id} />
    </section>
  );
}
