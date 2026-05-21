import type { ReactNode } from "react";

type CardProps = {
  title?: string;
  children: ReactNode;
};

export function Card({ title, children }: CardProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      {title ? (
        <h2 className="mb-4 text-sm font-semibold tracking-normal text-slate-950">
          {title}
        </h2>
      ) : null}
      {children}
    </section>
  );
}
