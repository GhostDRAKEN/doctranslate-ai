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
