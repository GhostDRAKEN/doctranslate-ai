import Link from "next/link";

export function Navbar() {
  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
        <Link href="/" className="text-sm font-semibold text-ink">
          DocTranslate AI
        </Link>
        <nav className="flex items-center gap-2 text-sm text-muted">
          <Link
            href="/"
            className="rounded-md px-3 py-2 hover:bg-surface hover:text-ink"
          >
            Accueil
          </Link>
          <Link
            href="/upload"
            className="rounded-md px-3 py-2 hover:bg-surface hover:text-ink"
          >
            Upload
          </Link>
        </nav>
      </div>
    </header>
  );
}
