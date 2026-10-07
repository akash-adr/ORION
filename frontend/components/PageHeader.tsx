export default function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <header className="mb-5">
      <h1 className="text-xl font-bold tracking-tight">{title}</h1>
      {children && <p className="mt-1 max-w-3xl text-sm text-fog">{children}</p>}
    </header>
  );
}
