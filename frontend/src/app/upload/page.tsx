"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { uploadDocument, type DocumentUploadResponse } from "@/lib/apiClient";

const constraints = [
  "PDF numerique uniquement",
  "10 Mo maximum",
  "10 pages maximum",
  "Texte selectionnable obligatoire",
];

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [uploadResult, setUploadResult] =
    useState<DocumentUploadResponse | null>(null);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadResult(null);
    setErrorMessage(null);
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setErrorMessage("Selectionnez un fichier PDF avant de continuer.");
      return;
    }

    setIsUploading(true);
    setErrorMessage(null);
    setUploadResult(null);

    try {
      const result = await uploadDocument(selectedFile);
      setUploadResult(result);
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "L'upload du document a echoue.",
      );
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-ink">Importer un PDF</h1>
        <p className="max-w-2xl text-sm leading-6 text-muted">
          Selectionnez un PDF numerique propre. Le traitement complet sera
          ajoute dans les prochaines etapes.
        </p>
      </div>

      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card title="Import PDF">
          <div className="space-y-5">
            <label
              htmlFor="pdf-upload"
              className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-line bg-white px-6 py-8 text-center hover:bg-surface"
            >
              <span className="text-sm font-medium text-ink">
                Selectionner un fichier PDF
              </span>
              <span className="mt-2 max-w-md text-sm leading-6 text-muted">
                Le drag and drop et la progression de traitement seront ajoutes
                plus tard.
              </span>
              <input
                id="pdf-upload"
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                onChange={handleFileChange}
              />
            </label>

            {selectedFile ? (
              <div className="rounded-md border border-line bg-surface px-4 py-3 text-sm">
                <p className="font-medium text-ink">{selectedFile.name}</p>
                <p className="mt-1 text-muted">
                  {(selectedFile.size / (1024 * 1024)).toFixed(2)} Mo
                </p>
              </div>
            ) : null}

            {errorMessage ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {errorMessage}
              </div>
            ) : null}

            {uploadResult ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                Document importe avec succes. Identifiant :{" "}
                <span className="font-medium">{uploadResult.document_id}</span>
              </div>
            ) : null}

            <div>
              <Button disabled={isUploading} onClick={handleUpload}>
                {isUploading ? "Upload en cours" : "Uploader le PDF"}
              </Button>
            </div>
          </div>
        </Card>

        <Card title="Contraintes visibles">
          <ul className="space-y-3">
            {constraints.map((item) => (
              <li key={item} className="flex items-center gap-3 text-sm">
                <span className="h-2 w-2 rounded-full bg-brand" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Card>
      </section>
    </div>
  );
}
