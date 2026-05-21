"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { getHealth } from "@/lib/apiClient";

type BackendState = "checking" | "connected" | "unavailable";

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
        : "Verification";

  const statusClass =
    backendState === "connected"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : backendState === "unavailable"
        ? "bg-red-50 text-red-700 ring-red-200"
        : "bg-slate-50 text-slate-500 ring-slate-200";

  return (
    <section className="flex min-h-[calc(100vh-9rem)] items-center justify-center">
      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <div
          className={`mb-8 inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1 ${statusClass}`}
        >
          {statusLabel}
        </div>

        <div className="mb-7 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-600 text-base font-bold text-white shadow-sm shadow-blue-600/25">
            D
          </span>
          <span className="text-sm font-semibold text-slate-950">
            DocTranslate AI
          </span>
        </div>

        <h1 className="max-w-3xl text-4xl font-semibold tracking-normal text-slate-950 sm:text-6xl">
          Traduisez vos PDF avec une mise en page preservee.
        </h1>

        <p className="mt-6 max-w-xl text-base leading-7 text-slate-600 sm:text-lg">
          Importez un PDF anglais, laissez l'IA traduire le contenu, puis
          recuperez un PDF francais pret a partager.
        </p>

        <div className="mt-9">
          <Button asChild className="min-h-12 px-6 text-base">
            <Link href="/upload">Importer un PDF</Link>
          </Button>
        </div>

        <div className="mt-10 flex items-center gap-3 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-500 shadow-sm">
          <span>PDF</span>
          <span className="text-slate-300">→</span>
          <span>Traduction IA</span>
          <span className="text-slate-300">→</span>
          <span>PDF traduit</span>
        </div>
      </div>
    </section>
  );
}
