"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import {
  generateDocx,
  generatePdf,
  getDocumentStatus,
  getDocxDownloadUrl,
  getPdfDownloadUrl,
  processDocument,
  uploadDocument,
  type DocumentDocxGenerationResponse,
  type DocumentPdfGenerationResponse,
  type DocumentStatusResponse,
  type DocumentUploadResponse,
} from "@/lib/apiClient";

const pollDelayMs = 2000;

function wait(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [uploadResult, setUploadResult] =
    useState<DocumentUploadResponse | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [documentStatus, setDocumentStatus] =
    useState<DocumentStatusResponse | null>(null);
  const [isGeneratingDocx, setIsGeneratingDocx] = useState(false);
  const [docxResult, setDocxResult] =
    useState<DocumentDocxGenerationResponse | null>(null);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [pdfResult, setPdfResult] =
    useState<DocumentPdfGenerationResponse | null>(null);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadResult(null);
    setDocumentStatus(null);
    setDocxResult(null);
    setPdfResult(null);
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
    setDocumentStatus(null);
    setDocxResult(null);
    setPdfResult(null);

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

  const handleStartProcessing = async () => {
    if (!uploadResult) {
      setErrorMessage("Importez un document avant de lancer le traitement.");
      return;
    }

    setIsProcessing(true);
    setErrorMessage(null);
    setDocxResult(null);
    setPdfResult(null);

    try {
      await processDocument(uploadResult.document_id);

      while (true) {
        const status = await getDocumentStatus(uploadResult.document_id);
        setDocumentStatus(status);

        if (status.status === "completed") {
          break;
        }

        if (status.status === "failed" || status.status === "expired") {
          throw new Error(
            status.error?.message ?? "Le traitement du document a echoue.",
          );
        }

        await wait(pollDelayMs);
      }
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Le traitement du document a echoue.",
      );
    } finally {
      setIsProcessing(false);
    }
  };

  const handleGenerateDocx = async () => {
    if (!uploadResult) {
      setErrorMessage("Importez un document avant de generer le DOCX.");
      return;
    }

    setIsGeneratingDocx(true);
    setErrorMessage(null);
    setDocxResult(null);

    try {
      const result = await generateDocx(uploadResult.document_id);
      setDocxResult(result);
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "La generation DOCX a echoue.",
      );
    } finally {
      setIsGeneratingDocx(false);
    }
  };

  const handleGeneratePdf = async () => {
    if (!uploadResult) {
      setErrorMessage("Importez un document avant de generer le PDF.");
      return;
    }

    setIsGeneratingPdf(true);
    setErrorMessage(null);
    setPdfResult(null);

    try {
      const result = await generatePdf(uploadResult.document_id);
      setPdfResult(result);
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "La generation PDF a echoue.",
      );
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div className="space-y-3 text-center">
        <p className="text-sm font-medium text-blue-600">DocTranslate AI</p>
        <h1 className="text-3xl font-semibold tracking-normal text-slate-950 sm:text-4xl">
          Importer un PDF
        </h1>
        <p className="mx-auto max-w-xl text-sm leading-6 text-slate-500">
          Ajoutez un document anglais et generez une version francaise en PDF.
        </p>
      </div>

      <section>
        <Card>
          <div className="space-y-6">
            <label
              htmlFor="pdf-upload"
              className="group flex min-h-56 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-6 py-10 text-center transition duration-200 hover:border-blue-300 hover:bg-blue-50/40"
            >
              <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-lg font-semibold text-blue-600 shadow-sm ring-1 ring-slate-200 transition group-hover:ring-blue-200">
                PDF
              </span>
              <span className="text-base font-medium text-slate-950">
                Selectionner un fichier PDF
              </span>
              <span className="mt-2 max-w-sm text-sm leading-6 text-slate-500">
                PDF numerique, 10 Mo maximum, 10 pages maximum.
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
              <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
                <p className="font-medium text-slate-950">{selectedFile.name}</p>
                <p className="mt-1 text-slate-500">
                  {(selectedFile.size / (1024 * 1024)).toFixed(2)} Mo
                </p>
              </div>
            ) : null}

            {errorMessage ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {errorMessage}
              </div>
            ) : null}

            {uploadResult ? (
              <div className="space-y-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-800">
                <p>
                  Document importe avec succes. Identifiant :{" "}
                  <span className="font-medium">{uploadResult.document_id}</span>
                </p>
                {!documentStatus ? (
                  <Button
                    disabled={isProcessing}
                    onClick={handleStartProcessing}
                    variant="secondary"
                  >
                    {isProcessing
                      ? "Traitement en cours..."
                      : "Lancer le traitement"}
                  </Button>
                ) : null}

                {documentStatus ? (
                  <div className="space-y-2">
                    <p>
                      Statut :{" "}
                      <span className="font-medium">
                        {documentStatus.status === "completed"
                          ? "Traitement termine"
                          : "Traitement en cours..."}
                      </span>
                    </p>
                    <p>
                      Etape : {documentStatus.current_step} -{" "}
                      {documentStatus.progress}%
                    </p>
                  </div>
                ) : null}

                {documentStatus?.status === "completed" ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      disabled={isGeneratingPdf}
                      onClick={handleGeneratePdf}
                      className="min-h-11"
                    >
                      {isGeneratingPdf ? "Generation en cours" : "Generer PDF"}
                    </Button>
                    <Button
                      disabled={isGeneratingDocx}
                      onClick={handleGenerateDocx}
                      variant="secondary"
                    >
                      {isGeneratingDocx ? "Generation DOCX" : "Generer DOCX"}
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : null}

            {pdfResult ? (
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4 text-sm text-emerald-800">
                <p className="font-medium">PDF genere avec succes.</p>
                <a
                  className="mt-2 inline-flex font-medium text-brand hover:underline"
                  href={getPdfDownloadUrl(pdfResult.document_id)}
                >
                  Telecharger le PDF
                </a>
              </div>
            ) : null}

            {docxResult ? (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm">
                <p className="font-medium text-slate-950">DOCX genere avec succes.</p>
                <a
                  className="mt-2 inline-flex text-brand hover:underline"
                  href={getDocxDownloadUrl(docxResult.document_id)}
                >
                  Telecharger le DOCX
                </a>
              </div>
            ) : null}

            <div className="flex justify-center">
              <Button
                disabled={isUploading || !selectedFile}
                onClick={handleUpload}
                className="min-h-12 px-6 text-base"
              >
                {isUploading ? "Upload en cours" : "Uploader le PDF"}
              </Button>
            </div>
          </div>
        </Card>
      </section>
    </div>
  );
}
