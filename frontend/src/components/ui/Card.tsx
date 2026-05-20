import type { ReactNode } from "react";

type CardProps = {
  title?: string;
  children: ReactNode;
};

export function Card({ title, children }: CardProps) {
  return (
    <section className="rounded-md border border-line bg-white p-5 shadow-soft">
      {title ? (
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-normal text-ink">
          {title}
        </h2>
      ) : null}
      {children}
    </section>
  );
}
