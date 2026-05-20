"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { getHealth } from "@/lib/apiClient";

type BackendState = "checking" | "connected" | "unavailable";

const constraints = [
  "PDF uniquement",
  "10 Mo maximum",
  "10 pages maximum",
  "Texte selectionnable requis",
];

export default function HomePage() {
  const [backendState, setBackendState] = useState<BackendState>("checking");

  useEffect(() => {
    let isMounted = true;

    getHealth()
      .then(() => {
        if (isMounted) {
          setBackendState("connected");
        }
      })
      .catch(() => {
        if (isMounted) {
          setBackendState("unavailable");
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const statusLabel =
    backendState === "connected"
      ? "Backend connecte"
      : backendState === "unavailable"
        ? "Backend indisponible"
        : "Verification du backend";

  const statusClass =
    backendState === "connected"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : backendState === "unavailable"
        ? "border-red-200 bg-red-50 text-red-700"
        : "border-slate-200 bg-white text-slate-600";

  return (
    <div className="space-y-8">
      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr] lg:items-start">
        <div className="space-y-5">
          <div
            className={`inline-flex rounded-md border px-3 py-1 text-sm font-medium ${statusClass}`}
          >
            {statusLabel}
          </div>
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold tracking-normal text-ink sm:text-4xl">
              DocTranslate AI
            </h1>
            <p className="max-w-2xl text-base leading-7 text-muted">
              Prototype web pour traduire des PDF numeriques anglais vers
              francais et reconstruire un document DOCX exploitable.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button asChild>
              <Link href="/upload">Preparer un PDF</Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href="/upload">Voir les contraintes</Link>
            </Button>
          </div>
        </div>

        <Card title="Contraintes MVP">
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

      <section className="grid gap-4 md:grid-cols-3">
        <Card title="Extraction structuree">
          <p className="text-sm leading-6 text-muted">
            Le MVP cible les titres, paragraphes, tableaux simples et images.
          </p>
        </Card>
        <Card title="DOCX prioritaire">
          <p className="text-sm leading-6 text-muted">
            Le resultat principal est un document editable. Le PDF reste
            optionnel.
          </p>
        </Card>
        <Card title="Validation explicite">
          <p className="text-sm leading-6 text-muted">
            Les zones a verifier seront signalees dans un rapport dedie.
          </p>
        </Card>
      </section>
    </div>
  );
}
