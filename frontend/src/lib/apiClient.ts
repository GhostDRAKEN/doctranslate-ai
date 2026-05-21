export type HealthResponse = {
  status: "ok";
  service: string;
};

export type ApiErrorResponse = {
  error: {
    code: string;
    message: string;
    details: unknown | null;
  };
};

export type DocumentUploadResponse = {
  document_id: string;
  filename: string;
  status: "uploaded";
};

export type DocumentDocxGenerationResponse = {
  document_id: string;
  status: "docx_generated";
  download_url: string;
};

export type DocumentPdfGenerationResponse = {
  document_id: string;
  status: "pdf_generated";
  download_url: string;
};

export type ProcessDocumentResponse = {
  job_id: string;
  document_id: string;
  status: "queued";
  translation_provider: string;
};

export type DocumentProcessingStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "completed"
  | "failed"
  | "expired";

export type DocumentJobStep =
  | "upload"
  | "analysis"
  | "extraction"
  | "domain_detection"
  | "translation"
  | "terminology_check"
  | "reconstruction"
  | "validation_report"
  | "done";

export type DocumentStatusResponse = {
  document_id: string;
  job_id: string | null;
  status: DocumentProcessingStatus;
  current_step: DocumentJobStep;
  progress: number;
  updated_at: string;
  error: {
    code: string;
    message: string;
  } | null;
};

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/api/health`, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Backend healthcheck failed");
  }

  return response.json() as Promise<HealthResponse>;
}

export async function uploadDocument(
  file: File,
): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${apiBaseUrl}/api/documents/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | ApiErrorResponse
      | null;
    throw new Error(
      payload?.error.message ?? "L'upload du document a echoue.",
    );
  }

  return response.json() as Promise<DocumentUploadResponse>;
}

export async function generateDocx(
  documentId: string,
): Promise<DocumentDocxGenerationResponse> {
  const response = await fetch(
    `${apiBaseUrl}/api/documents/${documentId}/generate-docx`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | ApiErrorResponse
      | null;
    throw new Error(
      payload?.error.message ?? "La generation DOCX a echoue.",
    );
  }

  return response.json() as Promise<DocumentDocxGenerationResponse>;
}

export async function generatePdf(
  documentId: string,
): Promise<DocumentPdfGenerationResponse> {
  const response = await fetch(
    `${apiBaseUrl}/api/documents/${documentId}/generate-pdf`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | ApiErrorResponse
      | null;
    throw new Error(payload?.error.message ?? "La generation PDF a echoue.");
  }

  return response.json() as Promise<DocumentPdfGenerationResponse>;
}

export function buildApiUrl(path: string): string {
  return `${apiBaseUrl}${path}`;
}

export async function processDocument(
  documentId: string,
): Promise<ProcessDocumentResponse> {
  const response = await fetch(
    `${apiBaseUrl}/api/documents/${documentId}/process`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        target_language: "fr",
        glossary: [],
      }),
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | ApiErrorResponse
      | null;
    throw new Error(
      payload?.error.message ?? "Le lancement du traitement a echoue.",
    );
  }

  return response.json() as Promise<ProcessDocumentResponse>;
}

export async function getDocumentStatus(
  documentId: string,
): Promise<DocumentStatusResponse> {
  const response = await fetch(
    `${apiBaseUrl}/api/documents/${documentId}/status`,
    {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    },
  );

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | ApiErrorResponse
      | null;
    throw new Error(
      payload?.error.message ?? "La recuperation du statut a echoue.",
    );
  }

  return response.json() as Promise<DocumentStatusResponse>;
}

export function getDocxDownloadUrl(documentId: string): string {
  return buildApiUrl(`/api/documents/${documentId}/download/docx`);
}

export function getPdfDownloadUrl(documentId: string): string {
  return buildApiUrl(`/api/documents/${documentId}/download/pdf`);
}
